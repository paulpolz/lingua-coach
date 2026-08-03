/**
 * Chat + onboarding client for the FastAPI backend.
 *
 * Mirrors docs/implementation-readiness.md §6 (API contract), §7 (SSE
 * contract), and §8 (JSON schemas), plus the `course_roadmap` v1 shape in
 * docs/tech_requirements/database.md ("learning_plans.roadmap"). There is no
 * shared-types package in MVP (see the plan's blind-spots table), so these
 * types are the frontend's manual mirror of the backend Pydantic models —
 * keep them in sync at integration checkpoints.
 */

import { apiFetch, toApiError } from "@/lib/api";

// ---------------------------------------------------------------------------
// Chat sessions + messages (readiness §6)
// ---------------------------------------------------------------------------

export type ChatSessionType = "onboarding" | "lesson";

export interface ChatSession {
  id: string;
  type: ChatSessionType;
  lesson_id: string | null;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
}

interface GetChatMessagesResponse {
  messages: ChatMessage[];
}

/** `POST /api/v1/chat/sessions` — create (or, for lesson sessions, resume) a chat session. */
export async function createChatSession(
  token: string | null,
  type: ChatSessionType,
  lessonId?: string
): Promise<ChatSession> {
  const response = await apiFetch("/api/v1/chat/sessions", token, {
    method: "POST",
    body: JSON.stringify(lessonId ? { type, lesson_id: lessonId } : { type }),
  });

  if (!response.ok) {
    throw await toApiError(response, "Failed to create chat session");
  }

  return response.json();
}

/** `GET /api/v1/chat/sessions/{id}/messages` — source of truth for the chat UI; always re-fetched on open. */
export async function getChatMessages(token: string | null, sessionId: string): Promise<ChatMessage[]> {
  const response = await apiFetch(`/api/v1/chat/sessions/${sessionId}/messages`, token);

  if (!response.ok) {
    throw await toApiError(response, "Failed to load chat messages");
  }

  const body: GetChatMessagesResponse = await response.json();
  return body.messages;
}

// ---------------------------------------------------------------------------
// Chat message metadata / JSON schemas (readiness §8)
// ---------------------------------------------------------------------------

export interface TimeBudget {
  minutes_per_session: number;
  sessions_per_week: number;
  intensity: "light" | "moderate" | "intensive" | string;
  optional_partner_minutes?: number;
}

export interface Correction {
  span: string;
  correction: string;
  type: string;
  note?: string;
}

export interface PlanUpdates {
  goal_summary?: string;
  level?: string;
  time_budget?: TimeBudget;
  topics?: string[];
  vocab_priorities?: string[];
  target_plan_days?: number;
  grammar_mastery?: Record<string, number>;
}

// ---------------------------------------------------------------------------
// course_roadmap v1 (database.md "learning_plans.roadmap")
// ---------------------------------------------------------------------------

export interface CourseRoadmapSummary {
  goal_outcome: string;
  goal_horizon: string;
  starting_level: string;
  target_plan_days: number;
  target_plan_days_range?: [number, number];
  pace_description?: string;
}

export interface CourseRoadmapMilestone {
  index: number;
  title: string;
  skill_developed?: string;
  why_now?: string;
  connects_to?: number[];
  success_criteria?: string;
  estimated_plan_days?: number;
}

export interface CourseRoadmapWeeklyActivity {
  id: string;
  label: string;
  minutes: number;
}

export interface CourseRoadmapWeeklyTemplate {
  minutes_per_session: number;
  activities: CourseRoadmapWeeklyActivity[];
  partner_session?: unknown;
  weekends?: string;
}

export interface CourseRoadmapThemeDay {
  block_day: number;
  grammar_focus?: string;
  vocab_theme?: string;
  input_type?: string;
  production_focus?: string;
  goal_specific_focus?: string;
}

export interface CourseRoadmapCurrentBlock {
  milestone_index: number;
  weeks?: number;
  focus_summary?: string;
  themes?: CourseRoadmapThemeDay[];
}

/** Full `course_roadmap` v1 object — draft (`done.metadata.course_roadmap_draft`) or accepted (`learning_plans.roadmap`). */
export interface CourseRoadmap {
  version: number;
  summary: CourseRoadmapSummary;
  milestones: CourseRoadmapMilestone[];
  weekly_template?: CourseRoadmapWeeklyTemplate;
  current_block?: CourseRoadmapCurrentBlock;
  learning_principles?: string[];
  adaptation_rules?: Record<string, string>;
  current_milestone_index?: number;
}

/** Chat `done` metadata. Onboarding sessions additionally carry `course_roadmap_draft` (coordination rule #3). */
export interface ChatMessageMetadata {
  corrections?: Correction[] | null;
  tips?: string[] | null;
  plan_updates?: PlanUpdates | null;
  suggest_finish?: boolean | null;
  course_roadmap_draft?: CourseRoadmap | null;
}

// ---------------------------------------------------------------------------
// SSE contract (readiness §7)
// ---------------------------------------------------------------------------

export interface SSETokenData {
  text: string;
}

export interface SSEDoneData {
  message_id: string;
  content: string;
  metadata: ChatMessageMetadata;
}

export interface SSEErrorData {
  code: string;
  message: string;
}

export interface StreamChatMessageHandlers {
  onToken?: (text: string) => void;
  onDone?: (data: SSEDoneData) => void;
  onError?: (data: SSEErrorData) => void;
}

interface ParsedSSEEvent {
  event: string;
  data: string;
}

/**
 * Splits a raw SSE buffer (`event: <name>\ndata: <json>\n\n`) into complete
 * events plus a remainder of unterminated trailing bytes. Pure/synchronous so
 * it can be unit-tested against synthetic chunks without a real network
 * stream.
 */
export function extractSSEEvents(buffer: string): { events: ParsedSSEEvent[]; remainder: string } {
  const normalized = buffer.replace(/\r\n/g, "\n");
  const blocks = normalized.split("\n\n");
  // The final element is either "" (buffer ended cleanly on a boundary) or a
  // partial event still waiting on more bytes — either way, it's not a
  // complete event yet, so it becomes the new remainder.
  const remainder = blocks.pop() ?? "";
  const events: ParsedSSEEvent[] = [];

  for (const block of blocks) {
    if (!block.trim()) continue;

    let eventName = "message";
    const dataLines: string[] = [];
    for (const line of block.split("\n")) {
      if (line.startsWith("event:")) {
        eventName = line.slice("event:".length).trim();
      } else if (line.startsWith("data:")) {
        dataLines.push(line.slice("data:".length).trim());
      }
    }

    if (dataLines.length > 0) {
      events.push({ event: eventName, data: dataLines.join("\n") });
    }
  }

  return { events, remainder };
}

function dispatchSSEEvent(event: ParsedSSEEvent, handlers: StreamChatMessageHandlers): void {
  let parsed: unknown;
  try {
    parsed = JSON.parse(event.data);
  } catch {
    handlers.onError?.({
      code: "MALFORMED_EVENT",
      message: `Received an unparsable ${event.event} event from the server.`,
    });
    return;
  }

  switch (event.event) {
    case "token": {
      const text = (parsed as Partial<SSETokenData> | null)?.text;
      if (typeof text === "string") handlers.onToken?.(text);
      break;
    }
    case "done":
      handlers.onDone?.(parsed as SSEDoneData);
      break;
    case "error":
      handlers.onError?.(parsed as SSEErrorData);
      break;
    default:
      // Unknown event name — ignore rather than break the stream, in case
      // the backend adds a forward-compatible event type later.
      break;
  }
}

/**
 * `POST /api/v1/chat/sessions/{id}/messages` with `Accept: text/event-stream`.
 *
 * `EventSource` doesn't support custom headers or POST bodies, so this
 * manually parses the SSE-over-fetch response: read the stream in chunks,
 * decode, split on blank lines, and dispatch `token` / `done` / `error`
 * events to the provided handlers. Never throws — all failure modes
 * (network error, non-2xx response, missing body, malformed frames, mid-
 * stream disconnects) are surfaced via `handlers.onError` so callers can
 * render a consistent inline error state.
 */
export async function streamChatMessage(
  token: string | null,
  sessionId: string,
  content: string,
  handlers: StreamChatMessageHandlers,
  signal?: AbortSignal
): Promise<void> {
  let response: Response;
  try {
    response = await apiFetch(`/api/v1/chat/sessions/${sessionId}/messages`, token, {
      method: "POST",
      headers: { Accept: "text/event-stream" },
      body: JSON.stringify({ content }),
      signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") return;
    handlers.onError?.({
      code: "NETWORK_ERROR",
      message: error instanceof Error ? error.message : "Could not reach the server.",
    });
    return;
  }

  if (!response.ok) {
    const apiError = await toApiError(response, "Message failed");
    handlers.onError?.({ code: apiError.code ?? "HTTP_ERROR", message: apiError.message });
    return;
  }

  if (!response.body) {
    handlers.onError?.({ code: "NO_BODY", message: "Server response had no body to stream." });
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const { events, remainder } = extractSSEEvents(buffer);
      buffer = remainder;
      for (const event of events) dispatchSSEEvent(event, handlers);
    }

    // Flush any trailing bytes the decoder buffered internally, then treat a
    // non-blank remainder as one last (possibly unterminated) event.
    buffer += decoder.decode();
    if (buffer.trim().length > 0) {
      const { events } = extractSSEEvents(`${buffer}\n\n`);
      for (const event of events) dispatchSSEEvent(event, handlers);
    }
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") return;
    handlers.onError?.({
      code: "STREAM_READ_ERROR",
      message: error instanceof Error ? error.message : "Lost connection while streaming the reply.",
    });
  }
}

// ---------------------------------------------------------------------------
// Onboarding accept (readiness §6)
// ---------------------------------------------------------------------------

export interface AcceptOnboardingResponse {
  onboarding_complete: boolean;
  plan_accepted_at: string;
}

/**
 * `POST /api/v1/onboarding/accept` — sends the session id plus the *cached*
 * `course_roadmap_draft` (verbatim, as last received in an SSE `done`
 * event) back to the backend. Per coordination rule #3 the backend persists
 * exactly what it's given, validated server-side — the client does not
 * infer or alter the roadmap.
 */
export async function acceptOnboarding(
  token: string | null,
  sessionId: string,
  courseRoadmap: CourseRoadmap
): Promise<AcceptOnboardingResponse> {
  const response = await apiFetch("/api/v1/onboarding/accept", token, {
    method: "POST",
    body: JSON.stringify({ session_id: sessionId, course_roadmap: courseRoadmap }),
  });

  if (!response.ok) {
    throw await toApiError(response, "Failed to accept plan");
  }

  return response.json();
}
