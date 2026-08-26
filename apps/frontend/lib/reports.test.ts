import { describe, expect, it } from "vitest";

import {
  displayReportMarkdown,
  parseReportSections,
  REPORT_SECTION_IDS,
  stackTableRows,
} from "./reports";

function wrap(id: string, inner: string): string {
  const body = inner.replace(/^\n+|\n+$/g, "");
  return body
    ? `<!-- section:${id} -->\n${body}\n<!-- /section:${id} -->`
    : `<!-- section:${id} -->\n<!-- /section:${id} -->`;
}

const PROGRESS_BODY = [
  "# Progress",
  "## Latest session",
  wrap("latest_session", "_Fills in after each accomplished lesson._"),
  "## Skill progress",
  wrap("progress_table", "| Category | Level |\n| --- | --- |\n| Grammar | B1 |"),
  "## Update log",
  wrap("update_log", ""),
].join("\n\n");

const ERRORS_BODY = [
  "# Error Log",
  wrap("pattern_tracker", "| Pattern | Status |\n| --- | --- |\n| articles | open |"),
  wrap("daily_log", ""),
  wrap("confusion_list", "| Word | Note |\n| --- | --- |\n| ser/estar | L1 |"),
].join("\n\n");

const ROADMAP_BODY = [
  "Intro wrapping prose that is not a section.",
  wrap("overview", "**Goal:** meetings"),
  wrap("milestones", "### 1. Diagnostic"),
  wrap("principles", "- active_recall"),
  wrap("scope_notes", ""),
].join("\n\n");

const FOUR_WEEK_BODY = [
  "# 4-Week Plan",
  wrap("block_overview", "**Current block:** diagnostic"),
  wrap("day_by_day", "### Day 1"),
  wrap("weekly_template", "60 min sessions"),
].join("\n\n");

describe("parseReportSections", () => {
  it("splits progress sections including an empty update_log", () => {
    const parsed = parseReportSections(PROGRESS_BODY);
    expect(parsed.sections.map((s) => s.id)).toEqual([...REPORT_SECTION_IDS.progress]);
    expect(parsed.sections[0].markdown).toBe("_Fills in after each accomplished lesson._");
    expect(parsed.sections[2].markdown).toBe("");
    expect(parsed.wrapping).toContain("# Progress");
    expect(parsed.wrapping).toContain("## Latest session");
  });

  it("splits error log, roadmap, and four-week-plan section ids", () => {
    expect(parseReportSections(ERRORS_BODY).sections.map((s) => s.id)).toEqual([
      ...REPORT_SECTION_IDS.errors_log,
    ]);
    expect(parseReportSections(ROADMAP_BODY).sections.map((s) => s.id)).toEqual([
      ...REPORT_SECTION_IDS.roadmap,
    ]);
    expect(parseReportSections(FOUR_WEEK_BODY).sections.map((s) => s.id)).toEqual([
      ...REPORT_SECTION_IDS.four_week_plan,
    ]);
  });

  it("keeps unknown wrapping prose outside markers", () => {
    const parsed = parseReportSections(ROADMAP_BODY);
    expect(parsed.wrapping).toContain("Intro wrapping prose that is not a section.");
    expect(parsed.wrapping).not.toContain("<!--");
    expect(parsed.sections.find((s) => s.id === "overview")?.markdown).toBe("**Goal:** meetings");
  });
});

describe("displayReportMarkdown", () => {
  it("strips section markers for leftover raw render", () => {
    const displayed = displayReportMarkdown(PROGRESS_BODY);
    expect(displayed).not.toMatch(/<!--/);
    expect(displayed).toContain("# Progress");
    expect(displayed).toContain("_Fills in after each accomplished lesson._");
    expect(displayed).toContain("| Grammar | B1 |");
  });
});

describe("stackTableRows", () => {
  it("turns a GFM header plus one data row into card fields", () => {
    const stacked = stackTableRows(
      ["Category", "Level", "Target", "Progress", "Notes"],
      [["Grammar", "B1", "B2", "on track", "articles"]],
    );
    expect(stacked).toEqual([
      {
        title: "Grammar",
        fields: [
          { label: "Level", value: "B1" },
          { label: "Target", value: "B2" },
          { label: "Progress", value: "on track" },
          { label: "Notes", value: "articles" },
        ],
      },
    ]);
  });
});
