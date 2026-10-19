/**
 * Lesson generation job client for the FastAPI backend.
 *
 * Mirrors docs/implementation-readiness.md §6 (`POST /lessons/start`,
 * `GET /jobs/{id}`, `GET /lessons/active`, `GET /lessons/{id}`) and the
 * `lesson_record` v1 `payload.curriculum` shape in
 * docs/tech_requirements/database.md — the plan's "blind spots" table calls
 * out that this nested `curriculum.slots` shape is canonical, not the flat
 * example under readiness §8. There is no shared-types package in MVP, so
 * these types are the frontend's manual mirror of the backend Pydantic
 * models — keep them in sync at integration checkpoints.
 */

import { ApiError, apiFetch, toApiError } from "@/lib/api";
import { isCsatValue } from "@/lib/quality";

// ---------------------------------------------------------------------------
// Jobs (readiness §6)
// ---------------------------------------------------------------------------

export type JobStatus = "pending" | "running" | "done" | "failed";

export interface Job {
  id: string;
  status: JobStatus;
  type: string;
  result_ref: string | null;
  error: string | null;
  created_at: string;
  updated_at: string;
}

/** `GET /api/v1/jobs/{job_id}`. */
export async function getJob(token: string | null, jobId: string): Promise<Job> {
  const response = await apiFetch(`/api/v1/jobs/${jobId}`, token);

  if (!response.ok) {
    throw await toApiError(response, "Failed to load job status");
  }

  return response.json();
}

// ---------------------------------------------------------------------------
// lesson_record v1 (database.md "lessons.payload")
// ---------------------------------------------------------------------------

export interface LessonCurriculumSlot {
  id: string;
  label: string;
  /** Brief description of planned drills — not full chat scripts. */
  exercise_set: string;
}

export interface LessonInputTask {
  type: string;
  topic: string;
  focus: string;
}

export interface LessonGoalSpecificTask {
  label: string;
  format: string;
}

/** Written when a lesson becomes `active` (after the generation job succeeds). */
export interface LessonCurriculum {
  lesson_goal: string;
  grammar_focus: string;
  vocab_theme: string;
  milestone_index: number;
  slots: LessonCurriculumSlot[];
  input_task: LessonInputTask;
  goal_specific_task: LessonGoalSpecificTask;
  exit_criteria: string[];
  partner_session: unknown | null;
}

export interface LessonSessionSummaryDeferredItem {
  slot_id: string;
  reason: string;
}

export interface LessonSessionSummaryFocusPatternResult {
  grammar_focus: string;
  met: boolean;
  note?: string;
}

/** Written on `POST /lessons/{id}/finish` (Phase 5) — `null` until then. */
export interface LessonSessionSummary {
  duration_minutes: number;
  completed_slots: string[];
  deferred_items: LessonSessionSummaryDeferredItem[];
  exit_criteria_met: boolean;
  performance_notes?: string;
  focus_pattern_result?: LessonSessionSummaryFocusPatternResult;
  resolved_pattern_types?: string[];
  new_pattern_types?: string[];
  vocab_themes_covered?: string[];
  learner_feedback?: string;
}

export interface LessonPayload {
  version: number;
  /** Absent/`null` while the lesson is still `generating`. */
  curriculum?: LessonCurriculum | null;
  session_summary?: LessonSessionSummary | null;
}

// ---------------------------------------------------------------------------
// Lessons (readiness §6)
// ---------------------------------------------------------------------------

export type LessonStatus = "generating" | "active" | "accomplished" | "failed";
export type PaceStatus = "on_pace" | "slipped";

export interface Lesson {
  id: string;
  lesson_number: number;
  status: LessonStatus;
  started_at: string | null;
  accomplished_at: string | null;
  pace_status: PaceStatus | null;
  payload: LessonPayload;
}

/** `GET /api/v1/lessons/active` — lesson object or `null` (no in-flight lesson). */
export async function getActiveLesson(token: string | null): Promise<Lesson | null> {
  const response = await apiFetch("/api/v1/lessons/active", token);

  if (!response.ok) {
    throw await toApiError(response, "Failed to load active lesson");
  }

  const body = await response.json();
  return (body as Lesson | null) ?? null;
}

/** `GET /api/v1/lessons/{lesson_id}`. */
export async function getLesson(token: string | null, lessonId: string): Promise<Lesson> {
  const response = await apiFetch(`/api/v1/lessons/${lessonId}`, token);

  if (!response.ok) {
    throw await toApiError(response, "Failed to load lesson");
  }

  return response.json();
}

// ---------------------------------------------------------------------------
// Start lesson (readiness §6) — the 409 conflict is a valid, expected state
// (one in-flight lesson per user), not an error condition to surface as a
// generic failure.
// ---------------------------------------------------------------------------

export interface StartLessonResponse {
  job_id: string;
  lesson_id: string;
  lesson_number: number;
}

/**
 * Thrown instead of a generic `ApiError` when `POST /lessons/start` returns
 * `409 ACTIVE_LESSON_EXISTS` — carries `activeLessonId` so the caller can
 * fetch that lesson and show a Resume state instead of an error banner.
 */
export class LessonConflictError extends ApiError {
  activeLessonId: string;

  constructor(message: string, activeLessonId: string) {
    super(409, message, "ACTIVE_LESSON_EXISTS");
    this.name = "LessonConflictError";
    this.activeLessonId = activeLessonId;
  }
}

/**
 * `POST /api/v1/lessons/start`.
 *
 * Resolves with `{ job_id, lesson_id, lesson_number }` on `202`. Throws
 * `LessonConflictError` (not a plain `ApiError`) on `409` when the response
 * includes `active_lesson_id`, so callers can special-case it; falls back to
 * a plain `ApiError` if the body is missing that field (e.g. contract drift).
 */
export async function startLesson(token: string | null): Promise<StartLessonResponse> {
  const response = await apiFetch("/api/v1/lessons/start", token, { method: "POST" });

  if (response.status === 409) {
    let detail = "An active lesson already exists.";
    let activeLessonId: string | null = null;
    try {
      const body = await response.json();
      if (typeof body?.detail === "string") detail = body.detail;
      if (typeof body?.active_lesson_id === "string") activeLessonId = body.active_lesson_id;
    } catch {
      // Response body wasn't JSON — keep the default message.
    }

    if (activeLessonId) {
      throw new LessonConflictError(detail, activeLessonId);
    }
    throw new ApiError(409, detail, "ACTIVE_LESSON_EXISTS");
  }

  if (!response.ok) {
    throw await toApiError(response, "Failed to start lesson");
  }

  return response.json();
}

// ---------------------------------------------------------------------------
// Stop lesson (readiness §6) — optional UI-convenience action. The lesson
// stays `active` either way (backend.md); this just lets the UI leave the
// chat and go back to the dashboard's Resume state.
// ---------------------------------------------------------------------------

/**
 * `POST /api/v1/lessons/{lesson_id}/stop` — expects `204 No Content`.
 * Callers should treat this as best-effort: per readiness §6 it's optional
 * and the UI may leave chat without calling it at all, so failures here
 * should not block navigation away from the lesson chat page.
 */
export async function stopLesson(token: string | null, lessonId: string): Promise<void> {
  const response = await apiFetch(`/api/v1/lessons/${lessonId}/stop`, token, { method: "POST" });

  if (!response.ok) {
    throw await toApiError(response, "Failed to stop lesson session");
  }
}

// ---------------------------------------------------------------------------
// Finish lesson (readiness §6) — the explicit "Finish lesson" action; always
// available while the lesson is `active` (early finish OK, frontend.md
// "Lesson lifecycle in UI"). Optional JSON: CSAT 1–5, free-text feedback,
// and completed slot ids. Empty body is allowed; rating must not block finish.
// ---------------------------------------------------------------------------

export interface FinishLessonRequest {
  learner_feedback?: string;
  /** Optional 1–5 lesson CSAT. Omit when the learner skips the rating. */
  csat?: number;
  completed_slot_ids?: string[];
}

export interface FinishLessonResponse {
  status: "accomplished";
  accomplished_at: string;
  pace_status: PaceStatus;
  schedule_updated: boolean;
}

/** Drop blank / out-of-range fields so finish stays valid with an empty rating. */
export function buildFinishLessonBody(input: FinishLessonRequest = {}): FinishLessonRequest {
  const body: FinishLessonRequest = {};
  const feedback = input.learner_feedback?.trim();
  if (feedback) body.learner_feedback = feedback;
  if (input.csat !== undefined && isCsatValue(input.csat)) body.csat = input.csat;
  if (input.completed_slot_ids && input.completed_slot_ids.length > 0) {
    body.completed_slot_ids = input.completed_slot_ids;
  }
  return body;
}

/** `POST /api/v1/lessons/{lesson_id}/finish` — JSON body, may be `{}`. */
export async function finishLesson(
  token: string | null,
  lessonId: string,
  input: FinishLessonRequest = {}
): Promise<FinishLessonResponse> {
  const response = await apiFetch(`/api/v1/lessons/${lessonId}/finish`, token, {
    method: "POST",
    body: JSON.stringify(buildFinishLessonBody(input)),
  });

  if (!response.ok) {
    throw await toApiError(response, "Failed to finish lesson");
  }

  return response.json();
}

/** One-line pace acknowledgment shown right after a successful finish. */
export function describeFinishResult(result: FinishLessonResponse): string {
  if (result.pace_status === "on_pace") {
    return "Lesson complete! You're on pace 🎉";
  }
  return result.schedule_updated
    ? "Lesson complete! This one slipped past the 24h window — plan adjusted."
    : "Lesson complete! This one slipped past the 24h window.";
}

// ---------------------------------------------------------------------------
// Finish hint hand-off — LessonChat finishes a lesson and redirects straight
// to the dashboard (frontend.md: nothing more to do in that chat). We carry
// the one-line pace acknowledgment across that redirect via sessionStorage
// rather than a query param, so the dashboard can show it once and it
// doesn't linger in the URL/history.
// ---------------------------------------------------------------------------

const FINISH_HINT_KEY = "lingua-coach:finish-hint";

/** Called by LessonChat right before navigating to `/dashboard` on finish. */
export function writeFinishHint(message: string): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.setItem(FINISH_HINT_KEY, message);
  } catch {
    // sessionStorage unavailable (e.g. privacy mode) — the dashboard just
    // won't show the acknowledgment banner; not worth failing navigation over.
  }
}

/** Called once by DashboardClient on mount; clears the hint after reading it. */
export function readAndClearFinishHint(): string | null {
  if (typeof window === "undefined") return null;
  try {
    const message = window.sessionStorage.getItem(FINISH_HINT_KEY);
    if (message) window.sessionStorage.removeItem(FINISH_HINT_KEY);
    return message;
  } catch {
    return null;
  }
}
