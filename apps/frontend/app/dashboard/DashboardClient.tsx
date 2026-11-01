"use client";

import { useAuth } from "@clerk/nextjs";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import {
  LessonConflictError,
  describeFinishResult,
  finishLesson,
  getActiveLesson,
  getLesson,
  isTimeBudgetRequired,
  readAndClearFinishHint,
  startLesson,
  stopLesson,
  type FinishLessonRequest,
} from "@/lib/lessons";
import FinishLessonDialog from "@/components/FinishLessonDialog";
import Button from "@/components/ui/Button";
import ActiveLessonHero from "./ActiveLessonHero";
import { stateForInFlightLesson, type DashboardState } from "./dashboard-state";
import DeskHero from "./DeskHero";
import GeneratingHero from "./GeneratingHero";
import PaceSummary from "./PaceSummary";
import TimeBudgetPrompt from "./TimeBudgetPrompt";
import { useGenerationPoll } from "./use-generation-poll";
import { useProgress } from "./use-progress";

/**
 * Dashboard state machine (see `DashboardState`): load the in-flight lesson,
 * start / poll generation, and resume, stop or finish the active lesson.
 * Sections render in their own components.
 */
export default function DashboardClient() {
  const { getToken } = useAuth();
  const router = useRouter();

  const [state, setState] = useState<DashboardState>({ phase: "loading" });
  // Bumped by the load-error retry button to re-run the initial-load effect
  // below without a full page reload.
  const [reloadCount, setReloadCount] = useState(0);
  const [isStopping, setIsStopping] = useState(false);
  const [stopError, setStopError] = useState<string | null>(null);
  const [isFinishing, setIsFinishing] = useState(false);
  const [finishError, setFinishError] = useState<string | null>(null);
  const [finishDialogOpen, setFinishDialogOpen] = useState(false);
  // Set either by a successful handleFinishLesson() call here, or carried
  // over from LessonChat's finish-then-redirect (readAndClearFinishHint).
  const [finishAckMessage, setFinishAckMessage] = useState<string | null>(() => readAndClearFinishHint());

  const { progress, error: progressError, reload: reloadProgress } = useProgress(reloadCount);
  useGenerationPoll(state, setState);

  useEffect(() => {
    let cancelled = false;

    async function loadActiveLesson() {
      setState({ phase: "loading" });
      try {
        const lesson = await getActiveLesson(await getToken());
        if (cancelled) return;
        setState(lesson ? stateForInFlightLesson(lesson) : { phase: "idle" });
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
      const result = await startLesson(await getToken());
      setState({
        phase: "generating",
        lessonId: result.lesson_id,
        lessonNumber: result.lesson_number,
        jobId: result.job_id,
        startedAt: Date.now(),
        timedOut: false,
      });
    } catch (error) {
      if (isTimeBudgetRequired(error)) {
        setState({ phase: "time-budget-required" });
        return;
      }
      if (error instanceof LessonConflictError) {
        // Not a UI bug — the backend already has an in-flight lesson for
        // this user. Fetch it and route into the matching state instead of
        // showing a generic error.
        try {
          const lesson = await getLesson(await getToken(), error.activeLessonId);
          setState(stateForInFlightLesson(lesson));
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
      await stopLesson(await getToken(), state.lesson.id);
    } catch (error) {
      setStopError(error instanceof Error ? error.message : "Failed to stop the session.");
    } finally {
      setIsStopping(false);
    }
  }, [state, isStopping, getToken]);

  // After finish the dashboard returns to idle; the backend owns lesson numbering.
  const handleFinishLesson = useCallback(
    async (feedback: FinishLessonRequest = {}) => {
      if (state.phase !== "active" || isFinishing) return;
      setIsFinishing(true);
      setFinishError(null);
      try {
        const result = await finishLesson(await getToken(), state.lesson.id, feedback);
        setFinishDialogOpen(false);
        setFinishAckMessage(describeFinishResult(result));
        setState({ phase: "idle" });
        reloadProgress();
      } catch (error) {
        setFinishError(error instanceof Error ? error.message : "Failed to finish the lesson.");
      } finally {
        setIsFinishing(false);
      }
    },
    [state, isFinishing, getToken, reloadProgress]
  );

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

      {state.phase === "time-budget-required" ? (
        <TimeBudgetPrompt onSaved={() => void handleStartLesson()} />
      ) : null}

      {state.phase === "generating" ? (
        <GeneratingHero
          lessonNumber={state.lessonNumber}
          startedAt={state.startedAt}
          timedOut={state.timedOut}
          onCheckAgain={handleCheckAgain}
        />
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
          onFinish={() => setFinishDialogOpen(true)}
          isFinishing={isFinishing}
          finishError={finishError}
        />
      ) : null}

      {state.phase !== "loading" && state.phase !== "load-error" ? (
        <PaceSummary progress={progress} error={progressError} />
      ) : null}

      <FinishLessonDialog
        open={finishDialogOpen}
        isSubmitting={isFinishing}
        onCancel={() => {
          if (!isFinishing) setFinishDialogOpen(false);
        }}
        onConfirm={(payload) => void handleFinishLesson(payload)}
      />
    </div>
  );
}
