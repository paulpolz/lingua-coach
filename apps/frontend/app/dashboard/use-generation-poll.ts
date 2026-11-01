"use client";

import { useAuth } from "@clerk/nextjs";
import { useRouter } from "next/navigation";
import { useEffect, type Dispatch, type SetStateAction } from "react";

import { isNotFoundError } from "@/lib/api";
import { getJob, getLesson } from "@/lib/lessons";
import type { DashboardState } from "./dashboard-state";

// Generation is one LLM call; the ceiling (~150s) clears the backend's 120s LLM timeout.
const POLL_INTERVAL_MS = 1800;
const MAX_POLL_ATTEMPTS = 85;

/**
 * While `state` is `generating`, poll the job (fresh start) or the lesson
 * itself (resumed after reload, where we never received a job_id) until
 * generation reaches a terminal state, then open the lesson chat.
 */
export function useGenerationPoll(state: DashboardState, setState: Dispatch<SetStateAction<DashboardState>>) {
  const { getToken } = useAuth();
  const router = useRouter();

  const lessonId = state.phase === "generating" ? state.lessonId : null;
  const jobId = state.phase === "generating" ? state.jobId : null;
  const timedOut = state.phase === "generating" ? state.timedOut : false;

  useEffect(() => {
    if (!lessonId || timedOut) return;

    let cancelled = false;
    let attempts = 0;
    const fail = (message: string) => setState({ phase: "generation-failed", message });

    const tick = async () => {
      attempts += 1;
      try {
        const token = await getToken();
        if (jobId) {
          const job = await getJob(token, jobId);
          if (cancelled) return;
          if (job.status === "done") {
            router.push(`/lesson/${lessonId}`);
            return;
          }
          if (job.status === "failed") {
            fail(job.error || "Lesson generation failed. Please try again.");
            return;
          }
        } else {
          const lesson = await getLesson(token, lessonId);
          if (cancelled) return;
          if (lesson.status === "active") {
            router.push(`/lesson/${lesson.id}`);
            return;
          }
          if (lesson.status === "failed") {
            fail("Lesson generation failed. Please try again.");
            return;
          }
        }
      } catch (error) {
        if (cancelled) return;
        // A job or lesson that doesn't exist (404 / 422) won't appear later.
        if (isNotFoundError(error)) {
          fail("This lesson is no longer available. Please start a new one.");
          return;
        }
        // Otherwise a transient network hiccup — stay in the generating
        // state; the attempt-count guard below still applies.
      }

      if (cancelled) return;
      if (attempts >= MAX_POLL_ATTEMPTS) {
        setState((prev) => (prev.phase === "generating" ? { ...prev, timedOut: true } : prev));
      }
    };

    const interval = setInterval(() => void tick(), POLL_INTERVAL_MS);
    void tick();

    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [lessonId, jobId, timedOut, getToken, router, setState]);
}
