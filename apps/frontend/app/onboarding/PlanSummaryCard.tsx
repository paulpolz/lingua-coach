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
  const range = summary.target_plan_days_range;

  return (
    <div className="relative flex h-full min-h-0 flex-col">
      {isRegenerating ? (
        <div className="absolute inset-0 z-10 flex items-center justify-center bg-background/80">
          <p className="text-sm text-muted">Updating your plan…</p>
        </div>
      ) : null}

      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mb-3 flex items-baseline gap-2">
          <h2 className="text-[13px] font-semibold leading-[18px] tracking-[-0.01em] text-foreground">
            Proposed plan
          </h2>
          {justUpdated && !isRegenerating ? <span className="text-[11px] text-muted">Updated</span> : null}
        </div>

        <dl className="space-y-3 text-sm">
          <div>
            <dt className="text-[11px] leading-4 text-muted">Goal</dt>
            <dd className="font-[550] leading-5 text-foreground">{summary.goal_outcome}</dd>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <dt className="text-[11px] leading-4 text-muted">Horizon</dt>
              <dd className="font-[550] leading-5 text-foreground">{summary.goal_horizon}</dd>
            </div>
            <div>
              <dt className="text-[11px] leading-4 text-muted">Level</dt>
              <dd className="font-[550] leading-5 text-foreground">{summary.starting_level}</dd>
            </div>
            <div>
              <dt className="text-[11px] leading-4 text-muted">Length</dt>
              <dd className="font-[550] leading-5 text-foreground">{summary.target_plan_days} days</dd>
            </div>
            <div>
              <dt className="text-[11px] leading-4 text-muted">Range</dt>
              <dd className="font-[550] leading-5 text-foreground">
                {range ? `${range[0]}–${range[1]} days` : "—"}
              </dd>
            </div>
          </div>
        </dl>

        {summary.pace_description ? (
          <p className="mt-3 text-[13px] leading-5 text-muted">{summary.pace_description}</p>
        ) : null}

        {milestones?.length > 0 ? (
          <ol className="mt-4">
            {milestones.map((milestone, index) => (
              <li
                key={milestone.index}
                className={`py-2 ${index > 0 ? "border-t border-border" : ""}`}
              >
                <div className="flex items-baseline justify-between gap-2">
                  <span className="text-sm font-[550] leading-5 text-foreground">{milestone.title}</span>
                  {milestone.estimated_plan_days ? (
                    <span className="shrink-0 text-xs text-muted">~{milestone.estimated_plan_days}d</span>
                  ) : null}
                </div>
                {milestone.success_criteria ? (
                  <p className="mt-0.5 text-xs leading-[18px] text-muted">{milestone.success_criteria}</p>
                ) : null}
              </li>
            ))}
          </ol>
        ) : null}

        {weeklyTemplate ? (
          <div className="mt-4">
            <p className="text-xs text-muted">Weekly session ({weeklyTemplate.minutes_per_session} min)</p>
            {weeklyTemplate.activities?.length ? (
              <p className="mt-1 text-sm leading-5 text-foreground">
                {weeklyTemplate.activities
                  .map((activity) => `${activity.label} ${activity.minutes}m`)
                  .join(" · ")}
              </p>
            ) : null}
          </div>
        ) : null}
      </div>

      {acceptError ? (
        <p className="mt-3 shrink-0 rounded-lg bg-danger-soft p-2 text-sm text-danger">{acceptError}</p>
      ) : null}

      <div className="mt-4 flex shrink-0 flex-col gap-2 sm:flex-row sm:items-center">
        <Button onClick={onAccept} disabled={actionsDisabled} className="sm:min-w-[8rem]">
          {isAccepting ? "Accepting…" : "Accept"}
        </Button>
        <Button variant="ghost" onClick={onChange} disabled={actionsDisabled} className="sm:min-w-[8rem]">
          Change
        </Button>
      </div>
    </div>
  );
}
