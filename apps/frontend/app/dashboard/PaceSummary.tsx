import type { PaceSummary as PaceSummaryValue, Progress } from "@/lib/progress";

/**
 * Dashboard "pace hints" section (frontend.md: "plan days done vs target,
 * on pace / behind, projected completion"). Fetched alongside the active
 * lesson in DashboardClient; degrades to a small inline note (or renders
 * nothing) rather than blocking the Start/Resume flow if it fails to load.
 */
export default function PaceSummary({
  progress,
  error,
}: {
  progress: Progress | null;
  error: string | null;
}) {
  if (error) {
    return (
      <p className="px-1 text-xs text-zinc-400 dark:text-zinc-600">
        Plan progress is unavailable right now.
      </p>
    );
  }

  if (!progress) return null;

  const { plan_days_done, target_plan_days, pace_summary, projected_completion_at, active_lesson } = progress;

  const hoursRemaining = active_lesson?.hours_remaining_in_pace_window;
  const pastPaceWindow = typeof hoursRemaining === "number" && hoursRemaining < 0;

  return (
    <div className="rounded-2xl border border-zinc-200 bg-white p-4 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm font-medium text-zinc-900 dark:text-zinc-100">
          {plan_days_done} / {target_plan_days} plan days
        </p>
        <PaceBadge value={pace_summary} />
      </div>

      {projected_completion_at ? (
        <p className="mt-1.5 text-xs text-zinc-500 dark:text-zinc-400">
          Projected finish: {formatDate(projected_completion_at)}
        </p>
      ) : null}

      {pastPaceWindow ? (
        <p className="mt-1.5 text-xs text-amber-700 dark:text-amber-400">
          Past your usual 24h pace window for the active lesson.
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

function PaceBadge({ value }: { value: PaceSummaryValue }) {
  // "not_started" isn't meaningful before the first lesson — hide it
  // entirely rather than showing an empty/neutral badge (spec).
  if (value === "not_started") return null;

  const styles: Record<Exclude<PaceSummaryValue, "not_started">, string> = {
    on_pace: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950/50 dark:text-emerald-300",
    behind: "bg-amber-100 text-amber-800 dark:bg-amber-950/50 dark:text-amber-300",
    ahead: "bg-blue-100 text-blue-800 dark:bg-blue-950/50 dark:text-blue-300",
  };

  const labels: Record<Exclude<PaceSummaryValue, "not_started">, string> = {
    on_pace: "On pace",
    behind: "Behind pace",
    ahead: "Ahead of schedule",
  };

  return (
    <span className={`rounded-full px-2.5 py-1 text-xs font-medium ${styles[value]}`}>{labels[value]}</span>
  );
}
