"use client";

import { useEffect, useId, useRef, useState } from "react";

import Button from "@/components/ui/Button";
import type { CsatValue } from "@/lib/quality";
import type { FinishLessonRequest } from "@/lib/lessons";

const CSAT_OPTIONS: CsatValue[] = [1, 2, 3, 4, 5];

export interface FinishLessonDialogProps {
  open: boolean;
  isSubmitting?: boolean;
  onCancel: () => void;
  onConfirm: (payload: FinishLessonRequest) => void;
}

/**
 * Optional 1–5 CSAT + free-text feedback before finishing a lesson.
 * Empty rating and empty comment are allowed — finish must not be blocked.
 * Form state lives in a child that unmounts when closed so fields reset cleanly.
 */
export default function FinishLessonDialog({
  open,
  isSubmitting = false,
  onCancel,
  onConfirm,
}: FinishLessonDialogProps) {
  if (!open) return null;
  return (
    <FinishLessonDialogForm isSubmitting={isSubmitting} onCancel={onCancel} onConfirm={onConfirm} />
  );
}

function FinishLessonDialogForm({
  isSubmitting,
  onCancel,
  onConfirm,
}: {
  isSubmitting: boolean;
  onCancel: () => void;
  onConfirm: (payload: FinishLessonRequest) => void;
}) {
  const titleId = useId();
  const textareaId = useId();
  const [csat, setCsat] = useState<CsatValue | null>(null);
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
        <p className="mt-1.5 text-sm leading-[22px] text-muted">
          Marks it accomplished. Any unfinished slots count as 0%. Rating is optional.
        </p>

        <fieldset className="mt-4">
          <legend className="text-[13px] font-[550] leading-[18px] text-foreground">
            How was this lesson?
          </legend>
          <div className="mt-2 flex gap-1.5" role="radiogroup" aria-label="Lesson rating from 1 to 5">
            {CSAT_OPTIONS.map((value) => {
              const selected = csat === value;
              return (
                <button
                  key={value}
                  type="button"
                  role="radio"
                  aria-checked={selected}
                  disabled={isSubmitting}
                  onClick={() => setCsat((current) => (current === value ? null : value))}
                  className={`flex h-9 w-9 items-center justify-center rounded-xl text-sm font-semibold [transition:transform_120ms_cubic-bezier(0.23,1,0.32,1),background-color_150ms_ease] active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/20 disabled:cursor-not-allowed disabled:opacity-50 ${
                    selected
                      ? "bg-accent text-white dark:text-stone-950"
                      : "border border-border-strong bg-surface text-foreground hover:bg-tutor-soft hover:text-tutor"
                  }`}
                >
                  {value}
                </button>
              );
            })}
          </div>
          <p className="mt-1.5 text-[11px] leading-4 text-muted">1 = poor · 5 = excellent. Skip if you prefer.</p>
        </fieldset>

        <label htmlFor={textareaId} className="mt-4 block text-[13px] font-[550] leading-[18px] text-foreground">
          Anything we should know?
        </label>
        <textarea
          id={textareaId}
          value={feedback}
          onChange={(event) => setFeedback(event.target.value)}
          disabled={isSubmitting}
          rows={3}
          placeholder="Optional — too hard, wrong language, more speaking…"
          className="mt-1.5 w-full resize-none rounded-xl border border-border-strong bg-background px-3.5 py-2.5 text-sm leading-[22px] text-foreground outline-none transition focus:border-accent focus:ring-2 focus:ring-accent/20 disabled:opacity-60"
        />

        <div className="mt-5 flex justify-end gap-2">
          <Button variant="ghost" onClick={onCancel} disabled={isSubmitting}>
            Cancel
          </Button>
          <Button
            onClick={() =>
              onConfirm({
                ...(csat ? { csat } : {}),
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
