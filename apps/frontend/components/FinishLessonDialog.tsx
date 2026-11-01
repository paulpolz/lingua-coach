"use client";

import { useEffect, useId, useRef, useState } from "react";

import Button from "@/components/ui/Button";
import type { LessonTiming } from "@/lib/chat";
import type { FinishLessonRequest } from "@/lib/lessons";

export interface FinishLessonDialogProps {
  open: boolean;
  /** Latest turn timing; `null` when unknown (e.g. finishing from the dashboard). */
  timing?: LessonTiming | null;
  isSubmitting?: boolean;
  onCancel: () => void;
  onConfirm: (payload: FinishLessonRequest) => void;
}

/** Matches the backend: `finished_early` is `shortfall_minutes > 1`. */
const EARLY_FINISH_SHORTFALL_MINUTES = 1;

/**
 * "You practiced about 8 of 15 min." plus what finishing means; an early finish
 * still counts. `timing` is from the last turn, while the backend counts up to
 * the click, so the numbers are approximate.
 */
function describeFinishTiming(timing: LessonTiming | null | undefined): string {
  if (!timing) return "Marks it accomplished.";
  const active = Math.max(0, Math.round(timing.active_minutes));
  const target = Math.round(timing.target_minutes);
  const practiced = `You practiced about ${active} of ${target} min.`;
  const shortfall = target - active;
  return shortfall > EARLY_FINISH_SHORTFALL_MINUTES
    ? `${practiced} It still counts; we'll note the ~${shortfall} min you missed.`
    : `${practiced} Marks it accomplished.`;
}

/**
 * Optional free-text feedback before finishing a lesson; an empty comment is fine.
 * Form state lives in a child that unmounts when closed so fields reset cleanly.
 */
export default function FinishLessonDialog({
  open,
  timing = null,
  isSubmitting = false,
  onCancel,
  onConfirm,
}: FinishLessonDialogProps) {
  if (!open) return null;
  return (
    <FinishLessonDialogForm
      body={describeFinishTiming(timing)}
      isSubmitting={isSubmitting}
      onCancel={onCancel}
      onConfirm={onConfirm}
    />
  );
}

function FinishLessonDialogForm({
  body,
  isSubmitting,
  onCancel,
  onConfirm,
}: {
  body: string;
  isSubmitting: boolean;
  onCancel: () => void;
  onConfirm: (payload: FinishLessonRequest) => void;
}) {
  const titleId = useId();
  const textareaId = useId();
  const [feedback, setFeedback] = useState("");
  const dialogRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !isSubmitting) onCancel();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [isSubmitting, onCancel]);

  useEffect(() => {
    dialogRef.current?.focus();
  }, []);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-foreground/25 px-5 py-8">
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        className="w-full max-w-[400px] rounded-2xl border border-border bg-surface p-5 shadow-md outline-none"
      >
        <h2 id={titleId} className="text-[17px] font-[590] leading-6 tracking-[-0.02em] text-foreground">
          Finish this lesson?
        </h2>
        <p className="mt-1.5 text-sm leading-[22px] text-muted">{body}</p>

        <label htmlFor={textareaId} className="mt-4 block text-[13px] font-[550] leading-[18px] text-foreground">
          Anything we should know?
        </label>
        <textarea
          id={textareaId}
          value={feedback}
          onChange={(event) => setFeedback(event.target.value)}
          disabled={isSubmitting}
          rows={3}
          placeholder="Optional — too hard, wrong language, more writing…"
          className="mt-1.5 w-full resize-none rounded-xl border border-border-strong bg-background px-3.5 py-2.5 text-sm leading-[22px] text-foreground outline-none transition focus:border-accent focus:ring-2 focus:ring-accent/20 disabled:opacity-60"
        />

        <div className="mt-5 flex justify-end gap-2">
          <Button variant="ghost" onClick={onCancel} disabled={isSubmitting}>
            Cancel
          </Button>
          <Button
            onClick={() =>
              onConfirm({
                ...(feedback.trim() ? { learner_feedback: feedback.trim() } : {}),
              })
            }
            disabled={isSubmitting}
          >
            {isSubmitting ? "Finishing…" : "Finish lesson"}
          </Button>
        </div>
      </div>
    </div>
  );
}
