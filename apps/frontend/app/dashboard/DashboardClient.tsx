"use client";

import { useAuth } from "@clerk/nextjs";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import {
  LessonConflictError,
  describeFinishResult,
  finishLesson,
  getActiveLesson,
  getJob,
  getLesson,
  readAndClearFinishHint,
  startLesson,
  stopLesson,
  type Lesson,
} from "@/lib/lessons";
import { getProgress, type Progress } from "@/lib/progress";
import PaceSummary from "./PaceSummary";

// Poll cadence + timeout guard for lesson generation (frontend.md "Do not
// block the whole app shell on lesson generation — poll in place"). The
// ceiling must clear the worst case of GEMINI_TIMEOUT_SECONDS (120s) *twice*
// (initial attempt + the 1 documented JSON-repair retry, readiness §11) plus
// request/DB overhead, with headroom — that's ~240s+ minimum.
const POLL_INTERVAL_MS = 1800;
const MAX_POLL_ATTEMPTS = 170;

type DashboardState =
  | { phase: "loading" }
  | { phase: "load-error"; message: string }
  | { phase: "idle" }
  | { phase: "starting" }
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

function formatElapsed(ms: number): string {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${seconds.toString().padStart(2, "0")}`;
}

export default function DashboardClient() {
  const { getToken } = useAuth();
  const router = useRouter();

  const [state, setState] = useState<DashboardState>({ phase: "loading" });
  const [now, setNow] = useState(() => Date.now());
  // Bumped by the load-error retry button to re-run the initial-load effect
  // below without a full page reload.
  const [reloadCount, setReloadCount] = useState(0);
  const [isStopping, setIsStopping] = useState(false);
  const [stopError, setStopError] = useState<string | null>(null);
  const [isFinishing, setIsFinishing] = useState(false);
  const [finishError, setFinishError] = useState<string | null>(null);
  // Set either by a successful handleFinishLesson() call here, or carried
  // over from LessonChat's finish-then-redirect (readAndClearFinishHint).
  const [finishAckMessage, setFinishAckMessage] = useState<string | null>(() => readAndClearFinishHint());

  // Pace/plan summary (frontend.md "Dashboard pace hints") — fetched
  // alongside the active lesson but never blocks the Start/Resume flow;
  // failures just hide the section (see PaceSummary.tsx).
  const [progress, setProgress] = useState<Progress | null>(null);
  const [progressError, setProgressError] = useState<string | null>(null);

  const loadProgress = useCallback(async () => {
    try {
      const token = await getToken();
      const result = await getProgress(token);
      setProgress(result);
      setProgressError(null);
    } catch (error) {
      setProgress(null);
      setProgressError(error instanceof Error ? error.message : "Failed to load progress.");
    }
  }, [getToken]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const token = await getToken();
        const result = await getProgress(token);
        if (cancelled) return;
        setProgress(result);
        setProgressError(null);
      } catch (error) {
        if (cancelled) return;
        setProgress(null);
        setProgressError(error instanceof Error ? error.message : "Failed to load progress.");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [getToken, reloadCount]);

  useEffect(() => {
    let cancelled = false;

    async function loadActiveLesson() {
      setState({ phase: "loading" });
      try {
        const token = await getToken();
        const lesson = await getActiveLesson(token);
        if (cancelled) return;
        if (!lesson) {
          setState({ phase: "idle" });
        } else if (lesson.status === "active") {
          setState({ phase: "active", lesson });
        } else {
          setState({
            phase: "generating",
            lessonId: lesson.id,
            lessonNumber: lesson.lesson_number,
            jobId: null,
            startedAt: Date.now(),
            timedOut: false,
          });
        }
      } catch (error) {
        if (cancelled) return;
        setState({
          phase: "load-error",
          message:
            error instanceof Error ? error.message : "Could not reach the server. Is the backend running?",
        });
      }
    }

    void loadActiveLesson();
    return () => {
      cancelled = true;
    };
  }, [getToken, reloadCount]);

  const handleStartLesson = useCallback(async () => {
    setState({ phase: "starting" });
    try {
      const token = await getToken();
      const result = await startLesson(token);
      setState({
        phase: "generating",
        lessonId: result.lesson_id,
        lessonNumber: result.lesson_number,
        jobId: result.job_id,
        startedAt: Date.now(),
        timedOut: false,
      });
    } catch (error) {
      if (error instanceof LessonConflictError) {
        // Not a UI bug — the backend already has an in-flight lesson for
        // this user. Fetch it and route into the matching state instead of
        // showing a generic error.
        try {
          const token = await getToken();
          const lesson = await getLesson(token, error.activeLessonId);
          if (lesson.status === "active") {
            setState({ phase: "active", lesson });
          } else {
            setState({
              phase: "generating",
              lessonId: lesson.id,
              lessonNumber: lesson.lesson_number,
              jobId: null,
              startedAt: Date.now(),
              timedOut: false,
            });
          }
        } catch (innerError) {
          setState({
            phase: "load-error",
            message:
              innerError instanceof Error
                ? innerError.message
                : "A lesson is already in progress, but it couldn't be loaded.",
          });
        }
        return;
      }
      setState({
        phase: "generation-failed",
        message: error instanceof Error ? error.message : "Failed to start the lesson.",
      });
    }
  }, [getToken]);

  const generatingLessonId = state.phase === "generating" ? state.lessonId : null;
  const generatingJobId = state.phase === "generating" ? state.jobId : null;
  const generatingTimedOut = state.phase === "generating" ? state.timedOut : false;

  // Poll the job (fresh start) or the lesson itself (resumed after reload,
  // where we never received a job_id) until generation reaches a terminal
  // state, then navigate into the placeholder lesson page.
  useEffect(() => {
    if (!generatingLessonId || generatingTimedOut) return;

    let cancelled = false;
    let attempts = 0;

    const tick = async () => {
      attempts += 1;
      try {
        const token = await getToken();
        if (generatingJobId) {
          const job = await getJob(token, generatingJobId);
          if (cancelled) return;
          if (job.status === "done") {
            router.push(`/lesson/${generatingLessonId}`);
            return;
          }
          if (job.status === "failed") {
            setState({
              phase: "generation-failed",
              message: job.error || "Lesson generation failed. Please try again.",
            });
            return;
          }
        } else {
          const lesson = await getLesson(token, generatingLessonId);
          if (cancelled) return;
          if (lesson.status === "active") {
            router.push(`/lesson/${lesson.id}`);
            return;
          }
          if (lesson.status === "failed") {
            setState({
              phase: "generation-failed",
              message: "Lesson generation failed. Please try again.",
            });
            return;
          }
        }
      } catch {
        // Transient network hiccup while polling — stay in the generating
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
  }, [generatingLessonId, generatingJobId, generatingTimedOut, getToken, router]);

  // Elapsed-time ticker for the generation progress UI.
  useEffect(() => {
    if (state.phase !== "generating") return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [state.phase]);

  const handleCheckAgain = useCallback(() => {
    setState((prev) => (prev.phase === "generating" ? { ...prev, timedOut: false, startedAt: Date.now() } : prev));
  }, []);

  // Optional UI-convenience action (backend.md): the lesson stays active
  // either way, so this just calls the endpoint and reports success/failure
  // inline — it does not change the dashboard's "active lesson" state.
  const handleStopSession = useCallback(async () => {
    if (state.phase !== "active" || isStopping) return;
    setIsStopping(true);
    setStopError(null);
    try {
      const token = await getToken();
      await stopLesson(token, state.lesson.id);
    } catch (error) {
      setStopError(error instanceof Error ? error.message : "Failed to stop the session.");
    } finally {
      setIsStopping(false);
    }
  }, [state, isStopping, getToken]);

  // "Finish lesson" — always available while the lesson is active
  // (frontend.md "Lesson lifecycle in UI"). On success the lesson is
  // accomplished server-side, so we drop straight back to `idle`: the
  // backend owns lesson numbering, so the next "Start lesson" click just
  // starts lesson N+1 with no state to track here.
  const handleFinishLesson = useCallback(async () => {
    if (state.phase !== "active" || isFinishing) return;
    setIsFinishing(true);
    setFinishError(null);
    try {
      const token = await getToken();
      const result = await finishLesson(token, state.lesson.id);
      setFinishAckMessage(describeFinishResult(result));
      setState({ phase: "idle" });
      void loadProgress();
    } catch (error) {
      setFinishError(error instanceof Error ? error.message : "Failed to finish the lesson.");
    } finally {
      setIsFinishing(false);
    }
  }, [state, isFinishing, getToken, loadProgress]);

  return (
    <div className="mx-auto flex w-full max-w-2xl flex-1 flex-col gap-4 overflow-y-auto p-4 sm:p-6">
      {finishAckMessage ? (
        <div className="flex items-center justify-between gap-3 rounded-xl bg-emerald-50 px-3 py-2.5 text-sm text-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-300">
          <span>{finishAckMessage}</span>
          <button
            type="button"
            onClick={() => setFinishAckMessage(null)}
            className="shrink-0 text-xs font-medium underline underline-offset-2"
          >
            Dismiss
          </button>
        </div>
      ) : null}

      {state.phase !== "loading" && state.phase !== "load-error" ? (
        <PaceSummary progress={progress} error={progressError} />
      ) : null}

      {state.phase === "loading" ? <LoadingCard label="Loading your dashboard…" /> : null}

      {state.phase === "load-error" ? (
        <ErrorCard message={state.message} onRetry={() => setReloadCount((n) => n + 1)} retryLabel="Retry" />
      ) : null}

      {state.phase === "idle" ? (
        <IdleCard onStart={() => void handleStartLesson()} />
      ) : null}

      {state.phase === "starting" ? <LoadingCard label="Starting your lesson…" /> : null}

      {state.phase === "generating" ? (
        <GeneratingCard
          lessonNumber={state.lessonNumber}
          elapsedMs={now - state.startedAt}
          timedOut={state.timedOut}
          onCheckAgain={handleCheckAgain}
        />
      ) : null}

      {state.phase === "generation-failed" ? (
        <ErrorCard
          message={state.message}
          onRetry={() => void handleStartLesson()}
          retryLabel="Try again"
        />
      ) : null}

      {state.phase === "active" ? (
        <ActiveLessonCard
          lesson={state.lesson}
          onResume={() => router.push(`/lesson/${state.lesson.id}`)}
          onStop={() => void handleStopSession()}
          isStopping={isStopping}
          stopError={stopError}
          onFinish={() => void handleFinishLesson()}
          isFinishing={isFinishing}
          finishError={finishError}
        />
      ) : null}
    </div>
  );
}

function LoadingCard({ label }: { label: string }) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-3 py-16 text-center">
      <div className="h-8 w-8 animate-spin rounded-full border-2 border-zinc-300 border-t-zinc-600 dark:border-zinc-700 dark:border-t-zinc-300" />
      <p className="text-sm text-zinc-500">{label}</p>
    </div>
  );
}

function ErrorCard({
  message,
  onRetry,
  retryLabel,
}: {
  message: string;
  onRetry: () => void;
  retryLabel: string;
}) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-3 py-16 text-center">
      <p className="max-w-md text-sm text-red-600 dark:text-red-400">{message}</p>
      <button
        type="button"
        onClick={onRetry}
        className="rounded-lg border border-zinc-300 px-4 py-2 text-sm font-medium hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800"
      >
        {retryLabel}
      </button>
    </div>
  );
}

function IdleCard({ onStart }: { onStart: () => void }) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-4 rounded-2xl border border-zinc-200 bg-white p-8 text-center shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
      <h1 className="text-lg font-semibold text-zinc-900 dark:text-zinc-100">Ready for your next lesson?</h1>
      <p className="max-w-sm text-sm text-zinc-500">
        We&apos;ll generate a lesson tailored to your plan and progress so far.
      </p>
      <button
        type="button"
        onClick={onStart}
        className="rounded-xl bg-zinc-900 px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-zinc-700 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-300"
      >
        Start lesson
      </button>
    </div>
  );
}

function GeneratingCard({
  lessonNumber,
  elapsedMs,
  timedOut,
  onCheckAgain,
}: {
  lessonNumber: number;
  elapsedMs: number;
  timedOut: boolean;
  onCheckAgain: () => void;
}) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-4 rounded-2xl border border-zinc-200 bg-white p-8 text-center shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
      <div className="h-8 w-8 animate-spin rounded-full border-2 border-zinc-300 border-t-zinc-600 dark:border-zinc-700 dark:border-t-zinc-300" />
      <div>
        <h1 className="text-lg font-semibold text-zinc-900 dark:text-zinc-100">
          Generating lesson {lessonNumber}…
        </h1>
        <p className="mt-1 text-sm text-zinc-500">{formatElapsed(elapsedMs)} elapsed</p>
      </div>
      {timedOut ? (
        <div className="mt-2 flex flex-col items-center gap-2">
          <p className="max-w-sm text-sm text-amber-700 dark:text-amber-400">
            This is taking longer than usual. It may still finish in the background.
          </p>
          <button
            type="button"
            onClick={onCheckAgain}
            className="rounded-lg border border-zinc-300 px-4 py-2 text-sm font-medium hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800"
          >
            Check again
          </button>
        </div>
      ) : null}
    </div>
  );
}

function ActiveLessonCard({
  lesson,
  onResume,
  onStop,
  isStopping,
  stopError,
  onFinish,
  isFinishing,
  finishError,
}: {
  lesson: Lesson;
  onResume: () => void;
  onStop: () => void;
  isStopping: boolean;
  stopError: string | null;
  onFinish: () => void;
  isFinishing: boolean;
  finishError: string | null;
}) {
  const curriculum = lesson.payload?.curriculum;

  return (
    <div className="rounded-2xl border border-blue-200 bg-blue-50 p-4 shadow-sm sm:p-5 dark:border-blue-900 dark:bg-blue-950/30">
      <div className="mb-3 flex items-center gap-2">
        <span className="inline-flex h-6 w-6 items-center justify-center rounded-full bg-blue-600 text-xs font-semibold text-white">
          {lesson.lesson_number}
        </span>
        <h2 className="text-sm font-semibold uppercase tracking-wide text-blue-800 dark:text-blue-300">
          Lesson in progress
        </h2>
      </div>

      <h1 className="text-lg font-semibold text-zinc-900 dark:text-zinc-100">
        Lesson {lesson.lesson_number}
        {curriculum?.lesson_goal ? ` — ${curriculum.lesson_goal}` : ""}
      </h1>

      {curriculum?.grammar_focus ? (
        <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
          <span className="font-medium">Grammar focus:</span> {curriculum.grammar_focus}
        </p>
      ) : null}

      {curriculum?.vocab_theme ? (
        <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
          <span className="font-medium">Vocab theme:</span> {curriculum.vocab_theme}
        </p>
      ) : null}

      {curriculum?.slots && curriculum.slots.length > 0 ? (
        <div className="mt-4">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
            Session outline
          </h3>
          <ol className="mt-2 space-y-2">
            {curriculum.slots.map((slot) => (
              <li key={slot.id} className="rounded-lg bg-white/70 p-2.5 text-sm dark:bg-zinc-900/40">
                <span className="font-medium text-zinc-900 dark:text-zinc-100">{slot.label}</span>
                <p className="mt-0.5 text-xs text-zinc-600 dark:text-zinc-400">{slot.exercise_set}</p>
              </li>
            ))}
          </ol>
        </div>
      ) : null}

      {stopError ? (
        <p className="mt-3 rounded-lg bg-red-50 p-2 text-xs text-red-700 dark:bg-red-950/40 dark:text-red-300">
          {stopError}
        </p>
      ) : null}

      {finishError ? (
        <p className="mt-3 rounded-lg bg-red-50 p-2 text-xs text-red-700 dark:bg-red-950/40 dark:text-red-300">
          {finishError}
        </p>
      ) : null}

      <div className="mt-5 flex flex-wrap gap-2">
        <button
          type="button"
          onClick={onResume}
          className="rounded-xl bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-blue-700"
        >
          Resume
        </button>
        <button
          type="button"
          onClick={onStop}
          disabled={isStopping}
          title="Leaves the session — the lesson stays active and you can resume anytime."
          className="rounded-xl border border-zinc-300 px-4 py-2.5 text-sm font-medium text-zinc-700 transition hover:bg-zinc-100 disabled:cursor-not-allowed disabled:opacity-60 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-800"
        >
          {isStopping ? "Stopping…" : "Stop session"}
        </button>
        <button
          type="button"
          onClick={() => {
            if (window.confirm("Mark this lesson accomplished? Any unfinished slots count as 0%.")) {
              onFinish();
            }
          }}
          disabled={isFinishing}
          title="Always available while the lesson is active — marks it accomplished and unlocks the next lesson."
          className="rounded-xl border border-emerald-300 bg-emerald-50 px-4 py-2.5 text-sm font-medium text-emerald-700 transition hover:bg-emerald-100 disabled:cursor-not-allowed disabled:opacity-60 dark:border-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-300 dark:hover:bg-emerald-950/60"
        >
          {isFinishing ? "Finishing…" : "Finish lesson"}
        </button>
      </div>
    </div>
  );
}
