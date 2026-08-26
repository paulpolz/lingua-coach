import { apiFetch, toApiError } from "@/lib/api";

export type ReportType = "progress" | "errors_log" | "roadmap" | "four_week_plan";

export interface UserReport {
  report_type: ReportType;
  body: string | null;
  updated_at: string | null;
}

/** Frozen section ids — must match backend `<!-- section:id -->` markers. */
export const REPORT_SECTION_IDS: Record<ReportType, readonly string[]> = {
  progress: ["latest_session", "progress_table", "update_log"],
  errors_log: ["pattern_tracker", "daily_log", "confusion_list"],
  roadmap: ["overview", "milestones", "principles", "scope_notes"],
  four_week_plan: ["block_overview", "day_by_day", "weekly_template"],
};

export const EMPTY_SECTION_COPY = "Fills in after your first lesson";

/** Patch anchors used by the backend (`<!-- section:id -->`). Not for learners. */
const SECTION_MARKER = /<!--\s*\/?section:[^>]*-->/g;
const SECTION_BLOCK =
  /<!--\s*section:([a-z0-9_]+)\s*-->([\s\S]*?)<!--\s*\/section:\1\s*-->/gi;

export interface ParsedReportSection {
  id: string;
  markdown: string;
}

export interface ParsedReport {
  sections: ParsedReportSection[];
  /** Markdown outside section markers (page titles, H2 labels, unknown prose). */
  wrapping: string;
}

export function displayReportMarkdown(body: string): string {
  return body.replace(SECTION_MARKER, "").replace(/\n{3,}/g, "\n\n").trim();
}

/**
 * Split a report body on `<!-- section:id -->` … `<!-- /section:id -->`.
 * Markers are not shown to learners; wrapping prose around them is kept.
 */
export function parseReportSections(body: string): ParsedReport {
  const sections: ParsedReportSection[] = [];
  const wrappingParts: string[] = [];
  const re = new RegExp(SECTION_BLOCK.source, "gi");
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = re.exec(body)) !== null) {
    const before = body.slice(lastIndex, match.index);
    if (before.trim()) wrappingParts.push(before.trim());
    sections.push({
      id: match[1],
      markdown: match[2].replace(/^\n+|\n+$/g, ""),
    });
    lastIndex = match.index + match[0].length;
  }

  const after = body.slice(lastIndex);
  if (after.trim()) wrappingParts.push(after.trim());

  return { sections, wrapping: wrappingParts.join("\n\n") };
}

/** Empty, whitespace-only, or a lone italic placeholder line. */
export function isEmptyReportSection(markdown: string): boolean {
  const trimmed = markdown.trim();
  if (!trimmed) return true;
  return /^[_*][^*\n_]+[_*]$/.test(trimmed);
}

export interface GfmTable {
  headers: string[];
  rows: string[][];
}

export interface StackedTableRow {
  title: string;
  fields: { label: string; value: string }[];
}

/** First column becomes the card title; remaining headers map to fields. */
export function stackTableRows(headers: string[], rows: string[][]): StackedTableRow[] {
  const fieldHeaders = headers.slice(1);
  return rows.map((row) => ({
    title: row[0] ?? "",
    fields: fieldHeaders.map((label, index) => ({
      label,
      value: row[index + 1] ?? "",
    })),
  }));
}

export type MarkdownChunk =
  | { kind: "prose"; markdown: string }
  | { kind: "table"; headers: string[]; rows: string[][] };

export function splitMarkdownTables(markdown: string): MarkdownChunk[] {
  const lines = markdown.split("\n");
  const chunks: MarkdownChunk[] = [];
  let prose: string[] = [];
  let inFence = false;

  const flushProse = () => {
    const text = prose.join("\n").trim();
    if (text) chunks.push({ kind: "prose", markdown: text });
    prose = [];
  };

  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (line.trim().startsWith("```")) {
      inFence = !inFence;
      prose.push(line);
      i += 1;
      continue;
    }
    if (!inFence && looksLikeTableStart(lines, i)) {
      flushProse();
      const { table, end } = consumeTable(lines, i);
      chunks.push({ kind: "table", headers: table.headers, rows: table.rows });
      i = end;
      continue;
    }
    prose.push(line);
    i += 1;
  }
  flushProse();
  return chunks;
}

export interface MarkdownBlock {
  heading: string | null;
  body: string;
}

/**
 * Split logs / milestone lists: ATX headings first, otherwise blank-line blocks.
 */
export function splitMarkdownBlocks(markdown: string): MarkdownBlock[] {
  const text = markdown.trim();
  if (!text) return [];

  if (/^#{1,6}\s+\S/m.test(text)) {
    const parts = text.split(/^(#{1,6}\s+.+)$/m);
    const blocks: MarkdownBlock[] = [];
    let heading: string | null = null;
    for (const part of parts) {
      if (!part) continue;
      const headingMatch = part.match(/^(#{1,6})\s+(.+)$/);
      if (headingMatch && !part.includes("\n")) {
        heading = headingMatch[2].trim();
        continue;
      }
      const body = part.replace(/^\n+|\n+$/g, "");
      if (heading || body) {
        blocks.push({ heading, body });
        heading = null;
      }
    }
    if (heading) blocks.push({ heading, body: "" });
    return blocks;
  }

  return text
    .split(/\n{2,}/)
    .map((body) => body.trim())
    .filter(Boolean)
    .map((body) => ({ heading: null, body }));
}

export async function getReport(token: string | null, reportType: ReportType): Promise<UserReport> {
  const response = await apiFetch(`/api/v1/reports/${reportType}`, token);
  if (!response.ok) {
    throw await toApiError(response, "Failed to load report");
  }
  return response.json();
}

function splitRow(line: string): string[] {
  let value = line.trim();
  if (value.startsWith("|")) value = value.slice(1);
  if (value.endsWith("|")) value = value.slice(0, -1);
  return value.split("|").map((cell) => cell.trim());
}

function isSeparatorRow(line: string): boolean {
  const cells = splitRow(line);
  if (cells.length === 0) return false;
  return cells.every((cell) => /^:?-{3,}:?$/.test(cell.replace(/\s/g, "")));
}

function looksLikeTableStart(lines: string[], index: number): boolean {
  if (index + 1 >= lines.length) return false;
  const row = lines[index].trim();
  const sep = lines[index + 1].trim();
  if (!row.includes("|") || !sep.includes("|")) return false;
  return isSeparatorRow(sep);
}

function consumeTable(lines: string[], start: number): { table: GfmTable; end: number } {
  const headers = splitRow(lines[start]);
  const rows: string[][] = [];
  let i = start + 2;
  while (i < lines.length) {
    const trimmed = lines[i].trim();
    if (!trimmed.includes("|") || isSeparatorRow(trimmed)) break;
    rows.push(splitRow(lines[i]));
    i += 1;
  }
  return { table: { headers, rows }, end: i };
}
