import { auth } from "@clerk/nextjs/server";

import AppHeader from "@/components/AppHeader";
import ReportBody from "../ReportBody";
import type { ReportIconName } from "../ReportIcons";
import type { ReportType } from "@/lib/reports";

const COPY: Record<
  string,
  { title: string; reportType: ReportType; description: string; icon: ReportIconName }
> = {
  progress: {
    title: "Progress",
    reportType: "progress",
    description: "Levels, targets, and a running log of what each lesson changed.",
    icon: "chart",
  },
  errors: {
    title: "Error Log",
    reportType: "errors_log",
    description: "Recurring patterns, day-by-day fixes, and sound-alike confusions.",
    icon: "warning",
  },
  roadmap: {
    title: "Roadmap",
    reportType: "roadmap",
    description: "Milestones from your starting point to your goal.",
    icon: "flag",
  },
  "four-week-plan": {
    title: "4-Week Plan",
    reportType: "four_week_plan",
    description: "Day-by-day grammar, vocabulary, listening, speaking, writing, and interview prep.",
    icon: "layers",
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
        <AppHeader title="Report" />
        <p className="p-6 text-sm text-muted">Unknown report.</p>
      </div>
    );
  }

  return (
    <div className="flex h-dvh flex-col overflow-hidden">
      <AppHeader title={meta.title} description={meta.description} />
      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto bg-background">
        <div className="mx-auto w-full max-w-[720px] px-7 pb-10 pt-9">
          <ReportBody
            reportType={meta.reportType}
            title={meta.title}
            description={meta.description}
            icon={meta.icon}
          />
        </div>
      </div>
    </div>
  );
}
