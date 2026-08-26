"use client";

import { useAuth } from "@clerk/nextjs";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState, type ReactNode } from "react";

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
import { reportClientError } from "@/lib/reportError";
import Button from "@/components/ui/Button";
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
        const message =
          error instanceof Error ? error.message : "Could not reach the server. Is the backend running?";
        setState({
          phase: "load-error",
          message,
        });
        reportClientError({
          code: "DASHBOARD_LOAD_ERROR",
          message,
          surface: "dashboard",
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
    <div className="mx-auto flex w-full max-w-[640px] flex-1 flex-col gap-7 overflow-y-auto bg-background px-7 pb-10 pt-9">
      {finishAckMessage ? (
        <div className="flex items-center justify-between gap-3">
          <p className="text-[13px] text-muted">{finishAckMessage}</p>
          <Button variant="ghost" size="sm" onClick={() => setFinishAckMessage(null)} className="shrink-0">
            Dismiss
          </Button>
        </div>
      ) : null}

      {state.phase === "loading" ? <p className="text-sm text-muted">Loading…</p> : null}

      {state.phase === "load-error" ? (
        <div className="flex flex-col items-start gap-3">
          <p className="text-sm text-muted">{state.message}</p>
          <Button variant="ghost" onClick={() => setReloadCount((n) => n + 1)}>
            Retry
          </Button>
        </div>
      ) : null}

      {state.phase === "idle" ? (
        <DeskHero
          title="Ready for your next lesson?"
          helper="We'll generate a lesson tailored to your plan and progress so far."
        >
          <Button onClick={() => void handleStartLesson()}>Start lesson</Button>
        </DeskHero>
      ) : null}

      {state.phase === "starting" ? (
        <DeskHero title="Ready for your next lesson?" helper="Starting…" helperClassName="text-[13px] text-muted" />
      ) : null}

      {state.phase === "generating" ? (
        <DeskHero
          title={`Generating lesson ${state.lessonNumber}…`}
          helper={formatElapsed(now - state.startedAt)}
          helperClassName="text-[13px] text-muted"
        >
          {state.timedOut ? (
            <div className="flex flex-col items-start gap-2">
              <p className="max-w-sm text-sm text-warning">
                This is taking longer than usual. It may still finish in the background.
              </p>
              <Button variant="ghost" onClick={handleCheckAgain}>
                Check again
              </Button>
            </div>
          ) : null}
        </DeskHero>
      ) : null}

      {state.phase === "generation-failed" ? (
        <div className="flex flex-col items-start gap-3">
          <p className="text-sm text-danger">{state.message}</p>
          <Button onClick={() => void handleStartLesson()}>Try again</Button>
        </div>
      ) : null}

      {state.phase === "active" ? (
        <ActiveLessonHero
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

      {state.phase !== "loading" && state.phase !== "load-error" ? (
        <PaceSummary progress={progress} error={progressError} />
      ) : null}
    </div>
  );
}

function DeskHero({
  title,
  helper,
  helperClassName = "text-sm leading-[22px] text-muted",
  children,
}: {
  title: string;
  helper?: string;
  helperClassName?: string;
  children?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-start gap-4">
      <h1 className="text-[22px] font-[590] leading-7 tracking-[-0.03em] text-foreground">{title}</h1>
      {helper ? <p className={helperClassName}>{helper}</p> : null}
      {children}
    </div>
  );
}

function ActiveLessonHero({
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
    <div className="flex flex-col items-start gap-4">
      <h1 className="text-[22px] font-[590] leading-7 tracking-[-0.03em] text-foreground">
        Resume lesson {lesson.lesson_number}?
      </h1>
      {curriculum?.lesson_goal || curriculum?.grammar_focus || curriculum?.vocab_theme ? (
        <div className="flex flex-col gap-1">
          {curriculum?.lesson_goal ? (
            <p className="text-sm leading-[22px] text-muted">{curriculum.lesson_goal}</p>
          ) : null}
          {curriculum?.grammar_focus ? (
            <p className="text-sm leading-[22px] text-muted">Grammar: {curriculum.grammar_focus}</p>
          ) : null}
          {curriculum?.vocab_theme ? (
            <p className="text-sm leading-[22px] text-muted">Vocab: {curriculum.vocab_theme}</p>
          ) : null}
        </div>
      ) : null}

      {stopError ? <p className="text-sm text-danger">{stopError}</p> : null}
      {finishError ? <p className="text-sm text-danger">{finishError}</p> : null}

      <div className="flex flex-wrap gap-2">
        <Button onClick={onResume}>Resume</Button>
        <Button
          variant="ghost"
          onClick={onStop}
          disabled={isStopping}
          title="Leaves the session — the lesson stays active and you can resume anytime."
        >
          {isStopping ? "Stopping…" : "Stop session"}
        </Button>
        <Button
          variant="ghost"
          onClick={() => {
            if (window.confirm("Mark this lesson accomplished? Any unfinished slots count as 0%.")) {
              onFinish();
            }
          }}
          disabled={isFinishing}
          title="Always available while the lesson is active — marks it accomplished and unlocks the next lesson."
        >
          {isFinishing ? "Finishing…" : "Finish lesson"}
        </Button>
      </div>
    </div>
  );
}
