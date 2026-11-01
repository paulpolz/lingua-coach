/**
 * Lesson and job client. Types mirror the backend by hand.
 */

import { ApiError, apiFetch, apiJson, apiRequest, toApiError } from "@/lib/api";

// ---------------------------------------------------------------------------
// Jobs
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
export function getJob(token: string | null, jobId: string): Promise<Job> {
  return apiJson(`/api/v1/jobs/${jobId}`, token, {}, "Failed to load job status");
}

// ---------------------------------------------------------------------------
// lesson_record v1 (database.md "lessons.payload")
// ---------------------------------------------------------------------------

/**
 * Written when a lesson becomes `active` (after the generation job succeeds).
 * Lessons generated before time-boxing also carry `slots` etc.; the UI ignores them.
 */
export interface LessonCurriculum {
  lesson_goal: string;
  grammar_focus: string;
  vocab_theme: string;
  milestone_index: number;
  new_vocabulary?: string[];
  review_patterns?: string[];
  goal_context?: string;
  practice_targets?: string[];
}

/** Written on finish; `null` until then. Older lessons have a different shape, so every new field is optional. */
export interface LessonSessionSummary {
  /** Active chat minutes (gaps capped by the backend's idle cap). */
  duration_minutes: number;
  target_minutes?: number | null;
  shortfall_minutes?: number;
  finished_early?: boolean;
  grammar_focus?: string | null;
  /** Item names the tutor reported `solid` / `shaky` (last result per item). */
  practiced_solid?: string[];
  practiced_shaky?: string[];
  resolved_pattern_types?: string[];
  new_pattern_types?: string[];
  new_vocabulary?: string[];
  vocab_themes_covered?: string[];
  learner_feedback?: string | null;
}

export interface LessonPayload {
  version: number;
  /** Absent/`null` while the lesson is still `generating`. */
  curriculum?: LessonCurriculum | null;
  /** Lesson length copied from the profile at generation; absent on older lessons. */
  target_minutes?: number | null;
  session_summary?: LessonSessionSummary | null;
}

// ---------------------------------------------------------------------------
// Lessons
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
  const body = await apiJson<Lesson | null>("/api/v1/lessons/active", token, {}, "Failed to load active lesson");
  return body ?? null;
}

/** `GET /api/v1/lessons/{lesson_id}`. Not found (404, or 422 for a malformed id): see `isNotFoundError`. */
export function getLesson(token: string | null, lessonId: string): Promise<Lesson> {
  return apiJson(`/api/v1/lessons/${lessonId}`, token, {}, "Failed to load lesson");
}

// ---------------------------------------------------------------------------
// Start lesson — the 409 conflict is a valid, expected state
// (one in-flight lesson per user), not an error condition to surface as a
// generic failure.
// ---------------------------------------------------------------------------

export interface StartLessonResponse {
  job_id: string;
  lesson_id: string;
  lesson_number: number;
}

/**
 * Error code for a profile without `time_budget.minutes_per_session`:
 * `409` from `POST /lessons/start` (legacy profile), `422` from onboarding accept.
 */
export const TIME_BUDGET_REQUIRED = "TIME_BUDGET_REQUIRED";

export function isTimeBudgetRequired(error: unknown): boolean {
  return error instanceof ApiError && error.code === TIME_BUDGET_REQUIRED;
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

async function readActiveLessonId(response: Response): Promise<string | null> {
  try {
    const body = await response.json();
    return typeof body?.active_lesson_id === "string" ? body.active_lesson_id : null;
  } catch {
    return null;
  }
}

/**
 * `POST /api/v1/lessons/start`.
 *
 * Resolves with `{ job_id, lesson_id, lesson_number }` on `202`. On `409`:
 * - `TIME_BUDGET_REQUIRED` → a plain `ApiError` with that code (see `isTimeBudgetRequired`);
 * - otherwise `LessonConflictError` when the body includes `active_lesson_id`,
 *   or a plain `ApiError` `ACTIVE_LESSON_EXISTS` if it's missing (contract drift).
 */
export async function startLesson(token: string | null): Promise<StartLessonResponse> {
  const response = await apiFetch("/api/v1/lessons/start", token, { method: "POST" });
  if (response.ok) return response.json();

  const error = await toApiError(response.clone(), "Failed to start lesson");
  if (response.status !== 409 || error.code === TIME_BUDGET_REQUIRED) throw error;

  const activeLessonId = await readActiveLessonId(response);
  if (activeLessonId) throw new LessonConflictError(error.message, activeLessonId);
  throw new ApiError(409, error.message, "ACTIVE_LESSON_EXISTS", error.requestId);
}

// ---------------------------------------------------------------------------
// Stop lesson — optional UI-convenience action. The lesson
// stays `active` either way (backend.md); this just lets the UI leave the
// chat and go back to the dashboard's Resume state.
// ---------------------------------------------------------------------------

/**
 * `POST /api/v1/lessons/{lesson_id}/stop` — expects `204 No Content`.
 * Callers should treat this as best-effort: it's optional
 * and the UI may leave chat without calling it at all, so failures here
 * should not block navigation away from the lesson chat page.
 */
export async function stopLesson(token: string | null, lessonId: string): Promise<void> {
  await apiRequest(`/api/v1/lessons/${lessonId}/stop`, token, { method: "POST" }, "Failed to stop lesson session");
}

// ---------------------------------------------------------------------------
// Finish lesson — always available while active, even before the time
// budget is used (the backend records the shortfall). Optional feedback;
// an empty body is allowed.
// ---------------------------------------------------------------------------

export interface FinishLessonRequest {
  learner_feedback?: string;
}

export interface FinishLessonResponse {
  status: "accomplished";
  accomplished_at: string;
  pace_status: PaceStatus;
  schedule_updated: boolean;
}

/** Drop blank fields. */
export function buildFinishLessonBody(input: FinishLessonRequest = {}): FinishLessonRequest {
  const body: FinishLessonRequest = {};
  const feedback = input.learner_feedback?.trim();
  if (feedback) body.learner_feedback = feedback;
  return body;
}

/** `POST /api/v1/lessons/{lesson_id}/finish` — JSON body, may be `{}`. */
export function finishLesson(
  token: string | null,
  lessonId: string,
  input: FinishLessonRequest = {}
): Promise<FinishLessonResponse> {
  return apiJson(
    `/api/v1/lessons/${lessonId}/finish`,
    token,
    { method: "POST", body: JSON.stringify(buildFinishLessonBody(input)) },
    "Failed to finish lesson"
  );
}

/** One-line pace acknowledgment shown right after a successful finish. */
export function describeFinishResult(result: FinishLessonResponse): string {
  if (result.pace_status === "on_pace") {
    return "Lesson complete! You're on pace 🎉";
  }
  return result.schedule_updated
    ? "Lesson complete! This one slipped past your pace window — plan adjusted."
    : "Lesson complete! This one slipped past your pace window.";
}

// ---------------------------------------------------------------------------
// Finish hint hand-off — LessonChat finishes a lesson and redirects straight
// to the dashboard (nothing more to do in that chat). We carry
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
