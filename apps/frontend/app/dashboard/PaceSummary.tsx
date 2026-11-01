import type { ReactNode } from "react";

import type { PaceSummary as PaceSummaryValue, Progress } from "@/lib/progress";

const PACE_LABELS: Record<Exclude<PaceSummaryValue, "not_started">, string> = {
  on_pace: "On pace",
  behind: "Behind pace",
  ahead: "Ahead of schedule",
};

/**
 * Pace strip: plan days done vs target, on pace / behind, projected completion.
 * Degrades to a small note instead of blocking Start/Resume.
 */
export default function PaceSummary({
  progress,
  error,
}: {
  progress: Progress | null;
  error: string | null;
}) {
  if (error) {
    return <p className="text-xs text-muted">Plan progress is unavailable right now.</p>;
  }

  if (!progress) return null;

  const { plan_days_done, target_plan_days, pace_summary, projected_completion_at, active_lesson } =
    progress;

  const hoursRemaining = active_lesson?.hours_remaining_in_pace_window;
  const pastPaceWindow = typeof hoursRemaining === "number" && hoursRemaining < 0;
  const fillPercent = Math.min(
    100,
    (plan_days_done / Math.max(target_plan_days, 1)) * 100
  );

  const meta: ReactNode[] = [];
  if (pace_summary !== "not_started") {
    meta.push(
      <span key="pace" className={pace_summary === "behind" ? "text-warning" : undefined}>
        {PACE_LABELS[pace_summary]}
      </span>
    );
  }
  if (projected_completion_at) {
    meta.push(<span key="projected">Projected {formatDate(projected_completion_at)}</span>);
  }

  return (
    <div>
      <div className="flex items-baseline justify-between gap-2 text-sm">
        <span className="text-foreground">Plan days</span>
        <span className="text-muted">
          {plan_days_done} / {target_plan_days}
        </span>
      </div>
      <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-surface-muted">
        <div className="h-full rounded-full bg-success" style={{ width: `${fillPercent}%` }} />
      </div>
      {meta.length > 0 ? (
        <p className="mt-2 text-xs text-muted">
          {meta.map((part, index) => (
            <span key={index}>
              {index > 0 ? " · " : null}
              {part}
            </span>
          ))}
        </p>
      ) : null}
      {pastPaceWindow ? (
        <p className="mt-1.5 text-xs text-warning">
          Past your pace window for the active lesson.
        </p>
      ) : null}
    </div>
  );
}

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  } catch {
    return iso;
  }
}
