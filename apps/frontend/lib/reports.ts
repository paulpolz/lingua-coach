import { apiFetch, toApiError } from "@/lib/api";

export type ReportType = "progress" | "errors_log" | "roadmap" | "four_week_plan";

export interface UserReport {
  report_type: ReportType;
  body: string | null;
  updated_at: string | null;
}

/** Patch anchors used by the backend (`<!-- section:id -->`). Not for learners. */
const SECTION_MARKER = /<!--\s*\/?section:[^>]*-->/g;

export function displayReportMarkdown(body: string): string {
  return body.replace(SECTION_MARKER, "").replace(/\n{3,}/g, "\n\n").trim();
}

export async function getReport(token: string | null, reportType: ReportType): Promise<UserReport> {
  const response = await apiFetch(`/api/v1/reports/${reportType}`, token);
  if (!response.ok) {
    throw await toApiError(response, "Failed to load report");
  }
  return response.json();
}