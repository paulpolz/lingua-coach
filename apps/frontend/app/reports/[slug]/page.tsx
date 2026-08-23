import { auth } from "@clerk/nextjs/server";

import AccountMenu from "@/components/AccountMenu";
import ReportBody from "../ReportBody";
import type { ReportType } from "@/lib/reports";

const COPY: Record<
  string,
  { title: string; reportType: ReportType; description: string }
> = {
  progress: {
    title: "Progress",
    reportType: "progress",
    description: "Levels, targets, and a running log of what each lesson changed.",
  },
  errors: {
    title: "Error Log",
    reportType: "errors_log",
    description: "Recurring patterns, day-by-day fixes, and sound-alike confusions.",
  },
  roadmap: {
    title: "Roadmap",
    reportType: "roadmap",
    description: "Milestones from diagnostic toward B2 simulation.",
  },
  "four-week-plan": {
    title: "4-Week Plan",
    reportType: "four_week_plan",
    description: "Day-by-day grammar, vocabulary, listening, speaking, writing, and interview prep.",
  },
};

export default async function ReportPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  await auth.protect();
  const { slug } = await params;
  const meta = COPY[slug];

  if (!meta) {
    return (
      <div className="flex h-dvh flex-col">
        <header className="flex items-center justify-between border-b border-zinc-200 px-4 py-3 dark:border-zinc-800">
          <h1 className="text-base font-semibold">Report</h1>
          <AccountMenu />
        </header>
        <p className="p-6 text-sm text-zinc-500">Unknown report.</p>
      </div>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
      <header className="flex shrink-0 items-center justify-between border-b border-zinc-200 px-4 py-3 dark:border-zinc-800">
        <div>
          <h1 className="text-base font-semibold">{meta.title}</h1>
          <p className="text-xs text-zinc-500">{meta.description}</p>
        </div>
        <AccountMenu />
      </header>
      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto px-4">
        <div className="mx-auto flex min-h-0 w-full max-w-3xl flex-1 flex-col">
          <ReportBody reportType={meta.reportType} />
        </div>
      </div>
    </div>
  );
}