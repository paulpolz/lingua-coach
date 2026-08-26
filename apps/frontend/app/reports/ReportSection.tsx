"use client";

import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Components } from "react-markdown";

import {
  EMPTY_SECTION_COPY,
  isEmptyReportSection,
  splitMarkdownBlocks,
  splitMarkdownTables,
} from "@/lib/reports";
import ReportIcon, { type ReportIconName } from "./ReportIcons";
import ReportTable from "./ReportTable";

export type ReportSectionVariant = "default" | "table" | "log" | "blocks";

const proseComponents: Components = {
  p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
  strong: ({ children }) => <strong className="font-[600]">{children}</strong>,
  em: ({ children }) => <em className="italic">{children}</em>,
  ul: ({ children }) => (
    <ul className="my-2 list-disc space-y-1 pl-5 marker:text-tutor">{children}</ul>
  ),
  ol: ({ children }) => (
    <ol className="my-2 list-decimal space-y-1 pl-5 marker:text-tutor">{children}</ol>
  ),
  li: ({ children }) => <li className="leading-snug">{children}</li>,
  h1: ({ children }) => (
    <h3 className="mb-2 text-base font-[550] tracking-[-0.01em] text-foreground">{children}</h3>
  ),
  h2: ({ children }) => (
    <h3 className="mb-2 text-sm font-[550] tracking-[-0.01em] text-foreground">{children}</h3>
  ),
  h3: ({ children }) => (
    <h3 className="mb-1.5 text-sm font-[550] tracking-[-0.01em] text-foreground">{children}</h3>
  ),
  blockquote: ({ children }) => (
    <blockquote className="my-2 border-l-2 border-border pl-3 text-muted">{children}</blockquote>
  ),
  a: ({ href, children }) => (
    <a href={href} className="text-accent underline-offset-2 hover:underline">
      {children}
    </a>
  ),
  table: ({ children }) => (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-sm leading-5">{children}</table>
    </div>
  ),
  th: ({ children }) => (
    <th className="border-b border-border px-2.5 py-2 text-left text-[11px] font-medium text-muted">
      {children}
    </th>
  ),
  td: ({ children }) => (
    <td className="border-b border-border px-2.5 py-2.5 align-top text-foreground">{children}</td>
  ),
  code: ({ children, className }) =>
    className ? (
      <code className="my-2 block overflow-x-auto rounded-md bg-surface-muted px-2 py-1 font-mono text-[0.85em]">
        {children}
      </code>
    ) : (
      <code className="rounded bg-surface-muted px-1 py-0.5 font-mono text-[0.85em]">{children}</code>
    ),
};

function Prose({ markdown }: { markdown: string }) {
  return (
    <div className="text-sm leading-[22px] text-foreground">
      <Markdown remarkPlugins={[remarkGfm]} components={proseComponents}>
        {markdown}
      </Markdown>
    </div>
  );
}

function MixedMarkdown({ markdown }: { markdown: string }) {
  const chunks = splitMarkdownTables(markdown);
  if (chunks.length === 0) return null;

  return (
    <div className="space-y-3">
      {chunks.map((chunk, index) =>
        chunk.kind === "table" ? (
          <ReportTable key={index} headers={chunk.headers} rows={chunk.rows} />
        ) : (
          <Prose key={index} markdown={chunk.markdown} />
        )
      )}
    </div>
  );
}

function BlockList({ markdown, log }: { markdown: string; log?: boolean }) {
  const blocks = splitMarkdownBlocks(markdown);
  if (blocks.length === 0) {
    return <p className="text-sm text-muted">{EMPTY_SECTION_COPY}</p>;
  }

  if (log) {
    return (
      <div className="space-y-3">
        {blocks.map((block, index) => (
          <div key={index} className="border-l border-border pl-3.5">
            {block.heading ? (
              <p className="text-[11px] leading-4 text-muted">{block.heading}</p>
            ) : null}
            {block.body ? (
              <div className={block.heading ? "mt-1" : undefined}>
                <MixedMarkdown markdown={block.body} />
              </div>
            ) : null}
          </div>
        ))}
      </div>
    );
  }

  return (
    <div>
      {blocks.map((block, index) => (
        <div key={index} className={`py-2.5 ${index > 0 ? "border-t border-border" : "pt-0"}`}>
          {block.heading ? (
            <p className="text-sm font-[550] leading-5 text-foreground">{block.heading}</p>
          ) : null}
          {block.body ? (
            <div className={block.heading ? "mt-1.5" : undefined}>
              <MixedMarkdown markdown={block.body} />
            </div>
          ) : null}
        </div>
      ))}
    </div>
  );
}

export default function ReportSection({
  label,
  icon,
  markdown,
  variant = "default",
}: {
  label: string;
  icon: ReportIconName;
  markdown: string;
  variant?: ReportSectionVariant;
}) {
  const empty = isEmptyReportSection(markdown);

  return (
    <section className="rounded-xl border border-border bg-surface p-4">
      <div className="mb-3 flex items-center gap-2.5">
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-tutor-soft text-tutor">
          <ReportIcon name={icon} />
        </span>
        <p className="text-[11px] leading-4 text-muted">{label}</p>
      </div>
      {empty ? (
        <p className="text-sm leading-[22px] text-muted">{EMPTY_SECTION_COPY}</p>
      ) : variant === "log" ? (
        <BlockList markdown={markdown} log />
      ) : variant === "blocks" ? (
        <BlockList markdown={markdown} />
      ) : (
        <MixedMarkdown markdown={markdown} />
      )}
    </section>
  );
}
