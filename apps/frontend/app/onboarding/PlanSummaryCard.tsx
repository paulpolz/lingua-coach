"use client";

import type { CourseRoadmap } from "@/lib/chat";
import Button from "@/components/ui/Button";

interface PlanSummaryCardProps {
  roadmap: CourseRoadmap;
  onAccept: () => void;
  onChange: () => void;
  isAccepting: boolean;
  isBusy?: boolean;
  isRegenerating?: boolean;
  justUpdated?: boolean;
  acceptError: string | null;
}

/**
 * Readable summary of a `course_roadmap` v1 draft.
 * Accept → dashboard; Change → keep this plan visible and refine it in chat.
 */
export default function PlanSummaryCard({
  roadmap,
  onAccept,
  onChange,
  isAccepting,
  isBusy = false,
  isRegenerating = false,
  justUpdated = false,
  acceptError,
}: PlanSummaryCardProps) {
  const { summary, milestones, weekly_template: weeklyTemplate } = roadmap;
  const actionsDisabled = isAccepting || isBusy || isRegenerating;

  return (
    <div className="relative w-full rounded-2xl border border-success/30 bg-success-soft p-4 shadow-sm sm:p-5">
      {isRegenerating ? (
        <div className="absolute inset-0 z-10 flex items-center justify-center rounded-2xl bg-success-soft/80">
          <div className="flex items-center gap-3 rounded-xl bg-surface px-4 py-3 shadow-sm">
            <div className="h-5 w-5 animate-spin rounded-full border-2 border-border border-t-tutor" />
            <p className="text-sm text-muted">Updating your plan…</p>
          </div>
        </div>
      ) : null}

      <div className="mb-3 flex items-center gap-2">
        <span className="inline-flex h-6 w-6 items-center justify-center rounded-full bg-success text-xs font-semibold text-white">
          ✓
        </span>
        <h2 className="text-sm font-semibold uppercase tracking-wide text-success">
          Proposed plan
        </h2>
        {justUpdated && !isRegenerating ? (
          <span className="rounded-md bg-surface px-2 py-0.5 text-xs font-medium text-success">
            Updated
          </span>
        ) : null}
      </div>

      <dl className="grid grid-cols-1 gap-3 text-sm sm:grid-cols-2">
        <div>
          <dt className="text-muted">Goal</dt>
          <dd className="font-medium text-foreground">{summary.goal_outcome}</dd>
        </div>
        <div>
          <dt className="text-muted">Horizon</dt>
          <dd className="font-medium text-foreground">{summary.goal_horizon}</dd>
        </div>
        <div>
          <dt className="text-muted">Starting level</dt>
          <dd className="font-medium text-foreground">{summary.starting_level}</dd>
        </div>
        <div>
          <dt className="text-muted">Target plan length</dt>
          <dd className="font-medium text-foreground">
            {summary.target_plan_days} days
            {summary.target_plan_days_range
              ? ` (${summary.target_plan_days_range[0]}–${summary.target_plan_days_range[1]})`
              : null}
          </dd>
        </div>
      </dl>

      {summary.pace_description ? (
        <p className="mt-3 text-sm text-foreground/80">{summary.pace_description}</p>
      ) : null}

      {milestones?.length > 0 ? (
        <div className="mt-4">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">Milestones</h3>
          <ol className="mt-2 space-y-2">
            {milestones.map((milestone) => (
              <li key={milestone.index} className="rounded-lg bg-surface/70 p-2.5 text-sm">
                <div className="flex items-baseline justify-between gap-2">
                  <span className="font-medium text-foreground">
                    {milestone.index + 1}. {milestone.title}
                  </span>
                  {milestone.estimated_plan_days ? (
                    <span className="shrink-0 text-xs text-muted">
                      ~{milestone.estimated_plan_days}d
                    </span>
                  ) : null}
                </div>
                {milestone.success_criteria ? (
                  <p className="mt-1 text-xs text-muted">{milestone.success_criteria}</p>
                ) : null}
              </li>
            ))}
          </ol>
        </div>
      ) : null}

      {weeklyTemplate ? (
        <div className="mt-4">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">
            Weekly session ({weeklyTemplate.minutes_per_session} min)
          </h3>
          <ul className="mt-2 flex flex-wrap gap-2">
            {weeklyTemplate.activities?.map((activity) => (
              <li
                key={activity.id}
                className="rounded-full bg-surface/70 px-2.5 py-1 text-xs text-foreground/80"
              >
                {activity.label} · {activity.minutes}m
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {acceptError ? (
        <p className="mt-4 rounded-lg bg-danger-soft p-2 text-sm text-danger">{acceptError}</p>
      ) : null}

      <div className="mt-4 flex flex-col gap-2 sm:flex-row sm:items-center">
        <Button onClick={onAccept} disabled={actionsDisabled} className="sm:min-w-[8rem]">
          {isAccepting ? "Accepting…" : "Accept"}
        </Button>
        <Button variant="secondary" onClick={onChange} disabled={actionsDisabled} className="sm:min-w-[8rem]">
          Change
        </Button>
      </div>
    </div>
  );
}
