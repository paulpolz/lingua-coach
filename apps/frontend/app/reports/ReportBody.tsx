"use client";

import { useAuth } from "@clerk/nextjs";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { ApiError } from "@/lib/api";
import {
  displayReportMarkdown,
  getReport,
  parseReportSections,
  REPORT_SECTION_IDS,
  type ReportType,
} from "@/lib/reports";
import { reportClientError } from "@/lib/reportError";
import Button from "@/components/ui/Button";
import ReportIcon, { type ReportIconName } from "./ReportIcons";
import ReportSection, { type ReportSectionVariant } from "./ReportSection";

interface SectionMeta {
  label: string;
  icon: ReportIconName;
  variant: ReportSectionVariant;
}

const SECTION_META: Record<string, SectionMeta> = {
  latest_session: { label: "Latest session", icon: "chart", variant: "default" },
  progress_table: { label: "Skill progress", icon: "sparkle", variant: "table" },
  update_log: { label: "Update log", icon: "list", variant: "log" },
  pattern_tracker: { label: "Pattern tracker", icon: "warning", variant: "table" },
  daily_log: { label: "Day-by-day log", icon: "calendar", variant: "log" },
  confusion_list: { label: "Sound-alike confusions", icon: "swap", variant: "table" },
  overview: { label: "Overview", icon: "flag", variant: "default" },
  milestones: { label: "Milestones", icon: "steps", variant: "blocks" },
  principles: { label: "Learning principles", icon: "lightbulb", variant: "default" },
  scope_notes: { label: "Scope notes", icon: "sliders", variant: "default" },
  block_overview: { label: "This block", icon: "layers", variant: "default" },
  day_by_day: { label: "Day by day", icon: "calendar", variant: "blocks" },
  weekly_template: { label: "Weekly template", icon: "clock", variant: "default" },
};

function fallbackLabel(sectionId: string): string {
  return sectionId.replace(/_/g, " ");
}

function ReportState({
  title,
  description,
  action,
  tone = "muted",
}: {
  title: string;
  description: string;
  action?: { label: string; onClick: () => void };
  tone?: "muted" | "danger";
}) {
  return (
    <div className="flex flex-col items-start gap-3 py-2">
      <h2 className="text-[22px] font-[590] leading-7 tracking-[-0.03em] text-foreground">{title}</h2>
      <p className={`max-w-[42ch] text-sm leading-[22px] ${tone === "danger" ? "text-danger" : "text-muted"}`}>
        {description}
      </p>
      {action ? <Button onClick={action.onClick}>{action.label}</Button> : null}
    </div>
  );
}

export default function ReportBody({
  reportType,
  title,
  description,
  icon,
}: {
  reportType: ReportType;
  title: string;
  description: string;
  icon: ReportIconName;
}) {
  const { getToken } = useAuth();
  const router = useRouter();
  const [body, setBody] = useState<string | null>(null);
  const [loadState, setLoadState] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState<string | null>(null);
  const [needsOnboarding, setNeedsOnboarding] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoadState("loading");
      setNeedsOnboarding(false);
      try {
        const token = await getToken();
        const report = await getReport(token, reportType);
        if (cancelled) return;
        setBody(report.body);
        setLoadState("ready");
      } catch (err) {
        if (cancelled) return;
        const message = err instanceof Error ? err.message : "Could not load this report.";
        setError(message);
        setNeedsOnboarding(
          err instanceof ApiError
            ? err.code === "ONBOARDING_INCOMPLETE"
            : /onboarding not complete/i.test(message)
        );
        setLoadState("error");
        reportClientError({
          code: "REPORT_LOAD_ERROR",
          message,
          surface: "unknown",
          meta: { report_type: reportType },
        });
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [getToken, reportType]);

  const parsed = useMemo(() => (body ? parseReportSections(body) : null), [body]);

  if (loadState === "loading") {
    return <p className="text-sm text-muted">Loading report…</p>;
  }
  if (loadState === "error" && needsOnboarding) {
    return (
      <ReportState
        title="Finish onboarding first"
        description="This report unlocks after a short chat to set your goal, level, and learning plan."
        action={{ label: "Go to Onboarding", onClick: () => router.push("/onboarding") }}
      />
    );
  }
  if (loadState === "error") {
    return (
      <ReportState
        title="This report isn’t available"
        description={error ?? "Something went wrong while loading this report."}
        tone="danger"
      />
    );
  }
  if (!body?.trim()) {
    return (
      <ReportState
        title="This fills in after your first lesson"
        description="Start a lesson from the dashboard. After you finish one, this report will start to build."
        action={{ label: "Go to Dashboard", onClick: () => router.push("/dashboard") }}
      />
    );
  }

  const sections = parsed?.sections ?? [];
  const byId = new Map(sections.map((section) => [section.id, section.markdown]));
  const orderedIds: string[] = [...REPORT_SECTION_IDS[reportType]];
  const extraIds = sections.map((section) => section.id).filter((id) => !orderedIds.includes(id));
  const sectionIds = sections.length > 0 ? [...orderedIds, ...extraIds] : [];

  return (
    <div className="flex flex-col gap-5">
      <div className="flex items-start gap-3">
        <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-tutor-soft text-tutor">
          <ReportIcon name={icon} className="h-5 w-5" />
        </span>
        <div className="min-w-0">
          <h2 className="text-[22px] font-[590] leading-7 tracking-[-0.03em] text-foreground">{title}</h2>
          <p className="mt-1 text-sm leading-[22px] text-muted">{description}</p>
        </div>
      </div>

      <div className="flex flex-col gap-3">
        {sectionIds.length > 0 ? (
          sectionIds.map((id) => {
            const meta = SECTION_META[id];
            return (
              <ReportSection
                key={id}
                label={meta?.label ?? fallbackLabel(id)}
                icon={meta?.icon ?? "list"}
                markdown={byId.get(id) ?? ""}
                variant={meta?.variant ?? "default"}
              />
            );
          })
        ) : (
          <ReportSection
            label={title}
            icon={icon}
            markdown={displayReportMarkdown(body)}
            variant="default"
          />
        )}
      </div>
    </div>
  );
}
