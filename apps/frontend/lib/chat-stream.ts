/**
 * SSE frames for `POST /api/v1/chat/sessions/{id}/messages/stream`.
 *
 * The structured payload is the model reply (`OnboardingReply` or `LessonReply`),
 * not the stored turn metadata. `course_roadmap` is the draft the plan card reads.
 * Timing and the suggest-finish time gate are applied when the row is saved;
 * they are copied from `GET .../messages` after `done`.
 */

import type {
  ChatMessageMetadata,
  Correction,
  CourseRoadmap,
  LessonTiming,
  PlanUpdates,
  PracticeResult,
} from "./chat";

/** An SSE `error` event, or a stream that ended before `done`. Mapped to `ApiError` by the client. */
export class ChatStreamError extends Error {
  readonly code?: string;

  constructor(message: string, code?: string) {
    super(message);
    this.name = "ChatStreamError";
    this.code = code;
  }
}

export interface ChatSseState {
  content: string;
  metadata: ChatMessageMetadata;
  messageId: string | null;
}

export interface SseFrame {
  event: string;
  data: unknown;
}

export function emptyChatSseState(): ChatSseState {
  return { content: "", metadata: {}, messageId: null };
}

export function readSseFrames(buffer: string): { frames: SseFrame[]; rest: string } {
  const parts = buffer.replace(/\r\n/g, "\n").split("\n\n");
  const rest = parts.pop() ?? "";
  const frames: SseFrame[] = [];
  for (const part of parts) {
    const frame = parseFrame(part);
    if (frame) frames.push(frame);
  }
  return { frames, rest };
}

function parseFrame(part: string): SseFrame | null {
  if (!part.trim()) return null;
  let event = "message";
  const dataLines: string[] = [];
  for (const line of part.split("\n")) {
    if (line.startsWith(":")) continue;
    if (line.startsWith("event:")) {
      event = line.slice("event:".length).trim();
      continue;
    }
    if (line.startsWith("data:")) {
      dataLines.push(line.slice("data:".length).replace(/^ /, ""));
    }
  }
  if (dataLines.length === 0) return null;
  try {
    return { event, data: JSON.parse(dataLines.join("\n")) };
  } catch {
    throw new ChatStreamError("The coach reply was interrupted.", "STREAM_INTERRUPTED");
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function stringList(value: unknown): string[] | undefined {
  if (!Array.isArray(value)) return undefined;
  return value.filter((item): item is string => typeof item === "string");
}

function correctionsFrom(value: unknown): Correction[] | undefined {
  if (!Array.isArray(value)) return undefined;
  const corrections: Correction[] = [];
  for (const item of value) {
    if (!isRecord(item)) continue;
    if (typeof item.span !== "string" || typeof item.correction !== "string") continue;
    corrections.push({
      span: item.span,
      correction: item.correction,
      type: typeof item.type === "string" ? item.type : "",
      note: typeof item.note === "string" ? item.note : undefined,
    });
  }
  return corrections;
}

function practicedFrom(value: unknown): PracticeResult[] | undefined {
  if (!Array.isArray(value)) return undefined;
  const practiced: PracticeResult[] = [];
  for (const item of value) {
    if (!isRecord(item) || typeof item.item !== "string") continue;
    if (item.aspect !== "grammar" && item.aspect !== "vocabulary" && item.aspect !== "review") continue;
    if (item.result !== "solid" && item.result !== "shaky") continue;
    practiced.push({ aspect: item.aspect, item: item.item, result: item.result });
  }
  return practiced;
}

function timingFrom(value: unknown): LessonTiming | undefined {
  if (!isRecord(value)) return undefined;
  if (typeof value.active_minutes !== "number" || typeof value.target_minutes !== "number") return undefined;
  return { active_minutes: value.active_minutes, target_minutes: value.target_minutes };
}

function roadmapFrom(value: unknown): CourseRoadmap | undefined {
  if (!isRecord(value) || !isRecord(value.summary) || !Array.isArray(value.milestones)) return undefined;
  return value as unknown as CourseRoadmap;
}

/** Map one structured reply onto the metadata the transcript already renders. */
export function metadataFromStructured(data: unknown): { content: string; metadata: ChatMessageMetadata } {
  if (!isRecord(data)) return { content: "", metadata: {} };
  const metadata: ChatMessageMetadata = {};
  const corrections = correctionsFrom(data.corrections);
  const tips = stringList(data.tips);
  const practiced = practicedFrom(data.practiced);
  const timing = timingFrom(data.timing);
  const roadmap = roadmapFrom(data.course_roadmap) ?? roadmapFrom(data.course_roadmap_draft);
  if (corrections) metadata.corrections = corrections;
  if (tips) metadata.tips = tips;
  if (practiced) metadata.practiced = practiced;
  if (timing) metadata.timing = timing;
  if (roadmap) metadata.course_roadmap_draft = roadmap;
  if (typeof data.suggest_finish === "boolean") metadata.suggest_finish = data.suggest_finish;
  if (isRecord(data.plan_updates)) metadata.plan_updates = data.plan_updates as PlanUpdates;
  return { content: typeof data.content === "string" ? data.content : "", metadata };
}

/**
 * Fold one SSE event into the in-flight coach reply.
 * Token deltas append. Structured `content` is the reply that will be stored,
 * so it replaces a tool preamble ("One moment.") when the two differ.
 * `error` throws and the caller must not keep going — that event replaces `done`.
 */
export function applyChatSseEvent(state: ChatSseState, event: string, data: unknown): ChatSseState {
  if (event === "error") {
    const body = isRecord(data) ? data : {};
    const detail = typeof body.detail === "string" && body.detail ? body.detail : "Something went wrong, try again.";
    const code = typeof body.code === "string" ? body.code : undefined;
    throw new ChatStreamError(detail, code);
  }
  if (event === "token") {
    const delta = isRecord(data) && typeof data.delta === "string" ? data.delta : "";
    if (!delta) return state;
    return { ...state, content: state.content + delta };
  }
  if (event === "structured") {
    const reply = metadataFromStructured(data);
    return {
      ...state,
      content: reply.content.trim() ? reply.content : state.content,
      metadata: reply.metadata,
    };
  }
  if (event === "done") {
    const messageId = isRecord(data) && typeof data.message_id === "string" ? data.message_id : "";
    if (!messageId) throw new ChatStreamError("The coach reply was interrupted.", "STREAM_INTERRUPTED");
    return { ...state, messageId };
  }
  return state;
}

/** Read the stream until `done`. Calls `onUpdate` when coach text or metadata changes. */
export async function consumeChatSse(
  body: ReadableStream<Uint8Array>,
  onUpdate: (update: { content: string; metadata: ChatMessageMetadata }) => void
): Promise<ChatSseState> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let pending = "";
  let state = emptyChatSseState();

  const take = (frames: SseFrame[]) => {
    for (const frame of frames) {
      const next = applyChatSseEvent(state, frame.event, frame.data);
      if (next.content !== state.content || next.metadata !== state.metadata) {
        onUpdate({ content: next.content, metadata: next.metadata });
      }
      state = next;
    }
  };

  try {
    while (true) {
      const { value, done } = await reader.read();
      if (value) pending += decoder.decode(value, { stream: !done });
      else if (done) pending += decoder.decode();
      const parsed = readSseFrames(pending);
      pending = parsed.rest;
      take(parsed.frames);
      if (done) break;
    }
  } finally {
    reader.releaseLock();
  }

  if (pending.trim()) {
    take(readSseFrames(`${pending}\n\n`).frames);
  }
  if (!state.messageId) {
    throw new ChatStreamError("The coach reply was interrupted.", "STREAM_INTERRUPTED");
  }
  return state;
}
