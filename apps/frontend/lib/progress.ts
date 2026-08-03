/**
 * Progress / pace summary client for the FastAPI backend.
 *
 * Mirrors docs/implementation-readiness.md §6 (`GET /progress`) — the
 * dashboard's plan-pacing surface (frontend.md "Dashboard pace hints").
 * There is no shared-types package in MVP, so these types are the
 * frontend's manual mirror of the backend Pydantic models — keep them in
 * sync at integration checkpoints.
 */

import { apiFetch, toApiError } from "@/lib/api";

/** Also used by `profile.schedule.pace_summary` (readiness §6 `GET /profile`). */
export type PaceSummary = "on_pace" | "behind" | "ahead" | "not_started";

export interface ProgressActiveLesson {
  id: string;
  lesson_number: number;
  started_at: string;
  /** May be negative once the 24h on-pace window has elapsed. */
  hours_remaining_in_pace_window: number;
}

export interface Progress {
  plan_days_done: number;
  target_plan_days: number;
  plan_slip_days: number;
  projected_completion_at: string | null;
  pace_summary: PaceSummary;
  active_lesson: ProgressActiveLesson | null;
}

/** `GET /api/v1/progress`. */
export async function getProgress(token: string | null): Promise<Progress> {
  const response = await apiFetch("/api/v1/progress", token);

  if (!response.ok) {
    throw await toApiError(response, "Failed to load progress");
  }

  return response.json();
}
