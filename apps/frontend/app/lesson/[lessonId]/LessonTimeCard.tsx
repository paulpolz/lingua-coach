import type { LessonTiming } from "@/lib/chat";

/**
 * Pinned "8 / 15 min" card with a thin progress bar. It changes only when a
 * turn returns new `metadata.timing` (the backend measures active minutes);
 * it is not a ticking timer.
 */
export default function LessonTimeCard({ timing }: { timing: LessonTiming }) {
  const active = Math.max(0, Math.round(timing.active_minutes));
  const target = Math.max(1, Math.round(timing.target_minutes));
  const percent = Math.min(100, Math.round((active / target) * 100));

  return (
    <aside className="w-[168px] max-w-[calc(100vw-2rem)] bg-surface-muted p-3">
      <p className="text-[11px] leading-4 text-muted">Lesson time</p>
      <p className="mt-0.5 text-sm leading-5 text-foreground">
        <span className="font-[590]">
          {active} / {target}
        </span>{" "}
        <span className="text-muted">min</span>
      </p>
      <div
        role="progressbar"
        aria-label="Lesson time used"
        aria-valuemin={0}
        aria-valuemax={target}
        aria-valuenow={Math.min(active, target)}
        aria-valuetext={`${active} of ${target} minutes`}
        className="mt-2 h-1 w-full overflow-hidden rounded-full bg-border"
      >
        <div className="h-full rounded-full bg-accent transition-[width]" style={{ width: `${percent}%` }} />
      </div>
    </aside>
  );
}
