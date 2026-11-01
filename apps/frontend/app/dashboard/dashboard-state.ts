import type { Lesson } from "@/lib/lessons";

export type DashboardState =
  | { phase: "loading" }
  | { phase: "load-error"; message: string }
  | { phase: "idle" }
  | { phase: "starting" }
  /** `POST /lessons/start` → 409 `TIME_BUDGET_REQUIRED`: ask for minutes, then start again. */
  | { phase: "time-budget-required" }
  | {
      phase: "generating";
      lessonId: string;
      lessonNumber: number;
      /** `null` when resumed from `GET /lessons/active` — we only learn `job_id` from a fresh `startLesson()` call, so this case polls the lesson itself instead. */
      jobId: string | null;
      startedAt: number;
      timedOut: boolean;
    }
  | { phase: "generation-failed"; message: string }
  | { phase: "active"; lesson: Lesson };

/** State for an in-flight lesson found on load or after a 409 conflict. */
export function stateForInFlightLesson(lesson: Lesson): DashboardState {
  if (lesson.status === "active") return { phase: "active", lesson };
  return {
    phase: "generating",
    lessonId: lesson.id,
    lessonNumber: lesson.lesson_number,
    jobId: null,
    startedAt: Date.now(),
    timedOut: false,
  };
}
