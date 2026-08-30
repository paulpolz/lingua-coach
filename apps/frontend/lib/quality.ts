/**
 * Learner quality signals — thumbs on assistant turns and lesson CSAT.
 *
 * Mirrors `POST /api/v1/quality/events` (204). Fire-and-forget: failures
 * must never break the transcript or block finish.
 */

import { apiFetch } from "@/lib/api";
import { reportClientError } from "@/lib/reportError";

export type QualityKind = "thumbs" | "lesson_csat";
export type QualitySurface = "onboarding" | "lesson" | "lesson_generation";
export type ThumbValue = 1 | -1;
export type CsatValue = 1 | 2 | 3 | 4 | 5;

export interface QualityThumbsValue {
  thumb: ThumbValue;
}

export interface QualityCsatScore {
  csat: CsatValue;
}

export interface QualityEventPayload {
  kind: QualityKind;
  surface: QualitySurface;
  session_id?: string;
  message_id?: string;
  lesson_id?: string | null;
  value: QualityThumbsValue | QualityCsatScore;
}

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** True when `id` is a persisted chat message id (SSE `done.message_id` / GET transcript), not a local streaming placeholder. */
export function isPersistedMessageId(id: string | null | undefined): boolean {
  return typeof id === "string" && UUID_RE.test(id);
}

export function canRateAssistantMessage(message: {
  role: string;
  id: string;
  isStreaming?: boolean;
  hidden?: boolean;
}): boolean {
  return (
    message.role === "assistant" &&
    !message.isStreaming &&
    !message.hidden &&
    isPersistedMessageId(message.id)
  );
}

export function isCsatValue(value: number): value is CsatValue {
  return Number.isInteger(value) && value >= 1 && value <= 5;
}

export function buildThumbsEvent(input: {
  surface: "onboarding" | "lesson";
  sessionId: string;
  messageId: string;
  lessonId?: string | null;
  thumb: ThumbValue;
}): QualityEventPayload {
  return {
    kind: "thumbs",
    surface: input.surface,
    session_id: input.sessionId,
    message_id: input.messageId,
    ...(input.lessonId ? { lesson_id: input.lessonId } : {}),
    value: { thumb: input.thumb },
  };
}

/**
 * `POST /api/v1/quality/events` — expects `204 No Content`.
 * Throws on network / non-2xx so callers can swallow; prefer `reportQualityEvent`.
 */
export async function submitQualityEvent(
  token: string | null,
  payload: QualityEventPayload
): Promise<void> {
  const response = await apiFetch("/api/v1/quality/events", token, {
    method: "POST",
    body: JSON.stringify(payload),
  });

  if (response.status === 204 || response.ok) return;

  const detail = `Quality event failed (status ${response.status})`;
  throw new Error(detail);
}

/** Fire-and-forget thumbs / CSAT. Never throws. Quiet telemetry on failure. */
export function reportQualityEvent(token: string | null, payload: QualityEventPayload): void {
  if (typeof window === "undefined") return;

  const surface =
    payload.surface === "onboarding" ? "onboarding" : payload.surface === "lesson" ? "lesson" : "unknown";

  void submitQualityEvent(token, payload).catch((error) => {
    reportClientError({
      code: "QUALITY_EVENT_FAILED",
      message: error instanceof Error ? error.message : "Failed to record quality event",
      surface,
      meta: {
        kind: payload.kind,
        quality_surface: payload.surface,
        message_id: payload.message_id ?? null,
        lesson_id: payload.lesson_id ?? null,
      },
    });
  });
}
