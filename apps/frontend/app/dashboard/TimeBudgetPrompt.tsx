"use client";

import { useAuth } from "@clerk/nextjs";
import { useId, useState, type FormEvent } from "react";

import Button from "@/components/ui/Button";
import { MAX_LESSON_MINUTES, MIN_LESSON_MINUTES, updateLessonMinutes } from "@/lib/profile";
import DeskHero from "./DeskHero";

/**
 * Shown when `POST /lessons/start` returns `409 TIME_BUDGET_REQUIRED` (a profile
 * saved before lesson length was required). Saves the minutes through
 * `PATCH /profile`, then calls `onSaved` so the dashboard retries the start.
 */
export default function TimeBudgetPrompt({ onSaved }: { onSaved: () => void }) {
  const { getToken } = useAuth();
  const inputId = useId();
  const hintId = useId();
  const [value, setValue] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const minutes = Number(value);
  const isValid =
    Number.isInteger(minutes) && minutes >= MIN_LESSON_MINUTES && minutes <= MAX_LESSON_MINUTES;

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (!isValid || isSaving) return;
    setIsSaving(true);
    setError(null);
    try {
      await updateLessonMinutes(await getToken(), minutes);
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save lesson length.");
      setIsSaving(false);
    }
  };

  return (
    <DeskHero
      title="How many minutes per lesson?"
      helper="Each lesson runs about this long. You can finish early any time."
    >
      <form onSubmit={(event) => void handleSubmit(event)} className="flex flex-col items-start gap-2">
        <label htmlFor={inputId} className="text-[13px] font-[550] leading-[18px] text-foreground">
          Minutes per lesson
        </label>
        <div className="flex items-center gap-2">
          <input
            id={inputId}
            type="number"
            inputMode="numeric"
            min={MIN_LESSON_MINUTES}
            max={MAX_LESSON_MINUTES}
            step={1}
            value={value}
            onChange={(event) => setValue(event.target.value)}
            disabled={isSaving}
            placeholder="15"
            aria-describedby={hintId}
            className="h-10 w-24 rounded-xl border border-border-strong bg-surface px-3.5 text-sm text-foreground outline-none transition focus:border-accent focus:ring-2 focus:ring-accent/20 disabled:opacity-60"
          />
          <Button type="submit" disabled={!isValid || isSaving}>
            {isSaving ? "Saving…" : "Save and start"}
          </Button>
        </div>
        <p id={hintId} className="text-xs text-muted">
          {MIN_LESSON_MINUTES}–{MAX_LESSON_MINUTES} minutes.
        </p>
        {error ? <p className="text-sm text-danger">{error}</p> : null}
      </form>
    </DeskHero>
  );
}
