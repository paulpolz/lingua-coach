/**
 * `GET /progress` client for the dashboard pace strip.
 */

import { apiJson } from "@/lib/api";

export type PaceSummary = "on_pace" | "behind" | "ahead" | "not_started";

export interface ProgressActiveLesson {
  id: string;
  lesson_number: number;
  started_at: string;
  /** May be negative once the on-pace window (`pace_window_hours`) has elapsed. */
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
export function getProgress(token: string | null): Promise<Progress> {
  return apiJson("/api/v1/progress", token, {}, "Failed to load progress");
}
