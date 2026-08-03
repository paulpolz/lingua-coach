"use client";

import type { CourseRoadmap } from "@/lib/chat";

interface PlanSummaryCardProps {
  roadmap: CourseRoadmap;
  onAccept: () => void;
  isAccepting: boolean;
  acceptError: string | null;
}

/**
 * Readable summary of a `course_roadmap` v1 draft (docs/tech_requirements/database.md).
 * Deliberately shows a subset of fields (goal, level, plan length, milestones,
 * weekly template) rather than the full JSON — per frontend.md's "thin brief,
 * not a full worksheet" guidance.
 */
export default function PlanSummaryCard({ roadmap, onAccept, isAccepting, acceptError }: PlanSummaryCardProps) {
  const { summary, milestones, weekly_template: weeklyTemplate } = roadmap;

  return (
    <div className="mx-auto w-full max-w-2xl rounded-2xl border border-emerald-200 bg-emerald-50 p-4 shadow-sm sm:p-5 dark:border-emerald-800 dark:bg-emerald-950/40">
      <div className="mb-3 flex items-center gap-2">
        <span className="inline-flex h-6 w-6 items-center justify-center rounded-full bg-emerald-600 text-xs font-semibold text-white">
          ✓
        </span>
        <h2 className="text-sm font-semibold uppercase tracking-wide text-emerald-800 dark:text-emerald-300">
          Proposed plan
        </h2>
      </div>

      <dl className="grid grid-cols-1 gap-3 text-sm sm:grid-cols-2">
        <div>
          <dt className="text-zinc-500 dark:text-zinc-400">Goal</dt>
          <dd className="font-medium text-zinc-900 dark:text-zinc-100">{summary.goal_outcome}</dd>
        </div>
        <div>
          <dt className="text-zinc-500 dark:text-zinc-400">Horizon</dt>
          <dd className="font-medium text-zinc-900 dark:text-zinc-100">{summary.goal_horizon}</dd>
        </div>
        <div>
          <dt className="text-zinc-500 dark:text-zinc-400">Starting level</dt>
          <dd className="font-medium text-zinc-900 dark:text-zinc-100">{summary.starting_level}</dd>
        </div>
        <div>
          <dt className="text-zinc-500 dark:text-zinc-400">Target plan length</dt>
          <dd className="font-medium text-zinc-900 dark:text-zinc-100">
            {summary.target_plan_days} days
            {summary.target_plan_days_range
              ? ` (${summary.target_plan_days_range[0]}–${summary.target_plan_days_range[1]})`
              : null}
          </dd>
        </div>
      </dl>

      {summary.pace_description ? (
        <p className="mt-3 text-sm text-zinc-700 dark:text-zinc-300">{summary.pace_description}</p>
      ) : null}

      {milestones?.length > 0 ? (
        <div className="mt-4">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
            Milestones
          </h3>
          <ol className="mt-2 space-y-2">
            {milestones.map((milestone) => (
              <li key={milestone.index} className="rounded-lg bg-white/70 p-2.5 text-sm dark:bg-zinc-900/40">
                <div className="flex items-baseline justify-between gap-2">
                  <span className="font-medium text-zinc-900 dark:text-zinc-100">
                    {milestone.index + 1}. {milestone.title}
                  </span>
                  {milestone.estimated_plan_days ? (
                    <span className="shrink-0 text-xs text-zinc-500 dark:text-zinc-400">
                      ~{milestone.estimated_plan_days}d
                    </span>
                  ) : null}
                </div>
                {milestone.success_criteria ? (
                  <p className="mt-1 text-xs text-zinc-600 dark:text-zinc-400">{milestone.success_criteria}</p>
                ) : null}
              </li>
            ))}
          </ol>
        </div>
      ) : null}

      {weeklyTemplate ? (
        <div className="mt-4">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
            Weekly session ({weeklyTemplate.minutes_per_session} min)
          </h3>
          <ul className="mt-2 flex flex-wrap gap-2">
            {weeklyTemplate.activities?.map((activity) => (
              <li
                key={activity.id}
                className="rounded-full bg-white/70 px-2.5 py-1 text-xs text-zinc-700 dark:bg-zinc-900/40 dark:text-zinc-300"
              >
                {activity.label} · {activity.minutes}m
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {acceptError ? (
        <p className="mt-4 rounded-lg bg-red-50 p-2 text-sm text-red-700 dark:bg-red-950/40 dark:text-red-300">
          {acceptError}
        </p>
      ) : null}

      <button
        type="button"
        onClick={onAccept}
        disabled={isAccepting}
        className="mt-4 w-full rounded-xl bg-emerald-600 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-60 sm:w-auto"
      >
        {isAccepting ? "Accepting…" : "Accept plan"}
      </button>
    </div>
  );
}
