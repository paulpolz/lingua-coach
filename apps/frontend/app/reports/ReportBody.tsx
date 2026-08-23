"use client";

import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useAuth } from "@clerk/nextjs";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { ApiError } from "@/lib/api";
import { displayReportMarkdown, getReport, type ReportType } from "@/lib/reports";
import { reportClientError } from "@/lib/reportError";
import Button from "@/components/ui/Button";

function ReportBanner({
  kicker,
  title,
  description,
  action,
}: {
  kicker: string;
  title: string;
  description: string;
  action?: { label: string; onClick: () => void };
}) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center py-10">
      <div className="box-border w-full max-w-md rounded-2xl border border-zinc-200 bg-white p-6 text-center shadow-sm sm:p-8 dark:border-zinc-700 dark:bg-zinc-900">
        <p className="text-xs font-semibold uppercase tracking-wide text-teal-700 dark:text-teal-400">
          {kicker}
        </p>
        <h2 className="mt-2 text-lg font-semibold text-zinc-900 dark:text-zinc-50">{title}</h2>
        <p className="mt-2 text-sm leading-relaxed text-zinc-500 dark:text-zinc-400">{description}</p>
        {action ? (
          <Button onClick={action.onClick} className="mt-5 w-full sm:w-auto">
            {action.label}
          </Button>
        ) : null}
      </div>
    </div>
  );
}

export default function ReportBody({ reportType }: { reportType: ReportType }) {
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

  if (loadState === "loading") {
    return <p className="text-sm text-zinc-500">Loading report…</p>;
  }
  if (loadState === "error" && needsOnboarding) {
    return (
      <ReportBanner
        kicker="Setup needed"
        title="Finish onboarding first"
        description="This report unlocks after a short chat to set your goal, level, and learning plan."
        action={{ label: "Go to Onboarding", onClick: () => router.push("/onboarding") }}
      />
    );
  }
  if (loadState === "error") {
    return (
      <ReportBanner
        kicker="Couldn’t load"
        title="This report isn’t available"
        description={error ?? "Something went wrong while loading this report."}
      />
    );
  }
  if (!body?.trim()) {
    return (
      <ReportBanner
        kicker="Nothing here yet"
        title="This fills in after your first lesson"
        description="Start a lesson from the dashboard. After you finish one, this report will start to build."
        action={{ label: "Go to Dashboard", onClick: () => router.push("/dashboard") }}
      />
    );
  }

  return (
    <div className="report-markdown">
      <Markdown remarkPlugins={[remarkGfm]}>{displayReportMarkdown(body)}</Markdown>
    </div>
  );
}
