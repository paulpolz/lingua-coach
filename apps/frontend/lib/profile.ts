/**
 * `PATCH /profile` client. Used when `POST /lessons/start` returns
 * `409 TIME_BUDGET_REQUIRED` for a profile saved before lesson length was required.
 */

import { apiRequest } from "@/lib/api";

/** Bounds of `time_budget.minutes_per_session` on the backend. */
export const MIN_LESSON_MINUTES = 5;
export const MAX_LESSON_MINUTES = 180;

/** `PATCH /api/v1/profile` with `{time_budget: {minutes_per_session}}`. The response body is not used. */
export async function updateLessonMinutes(token: string | null, minutes: number): Promise<void> {
  await apiRequest(
    "/api/v1/profile",
    token,
    { method: "PATCH", body: JSON.stringify({ time_budget: { minutes_per_session: minutes } }) },
    "Failed to save lesson length"
  );
}
