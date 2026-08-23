"use client";

import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Components } from "react-markdown";

import type { ChatMessageMetadata } from "@/lib/chat";

const chatMarkdownComponents: Components = {
  p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
  strong: ({ children }) => <strong className="font-bold">{children}</strong>,
  em: ({ children }) => <em className="italic">{children}</em>,
  ul: ({ children }) => <ul className="my-2 list-disc space-y-1 pl-5 marker:text-tutor">{children}</ul>,
  ol: ({ children }) => (
    <ol className="my-2 list-decimal space-y-1 pl-5 marker:text-tutor">{children}</ol>
  ),
  li: ({ children }) => <li className="leading-snug">{children}</li>,
  h1: ({ children }) => <h1 className="mb-2 text-base font-bold">{children}</h1>,
  h2: ({ children }) => <h2 className="mb-2 text-sm font-bold">{children}</h2>,
  h3: ({ children }) => <h3 className="mb-1.5 text-sm font-bold">{children}</h3>,
  blockquote: ({ children }) => (
    <blockquote className="my-2 border-l-2 border-border pl-3 text-muted">{children}</blockquote>
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

/** A message rendered in a chat transcript — either persisted or still streaming in. */
export interface DisplayMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  metadata?: ChatMessageMetadata | null;
  /** Client-only, in-flight assistant reply — not yet finalized by a `done` event. */
  isStreaming?: boolean;
  /** Hide this bubble (e.g. silent onboarding Start trigger). */
  hidden?: boolean;
}

/**
 * Shared chat bubble used by both onboarding and lesson chat. Tutor messages
 * get a soft teal accent + label; learner messages are right-aligned dark.
 * Corrections / tips from `done.metadata` render as a scannable brief under
 * the bubble.
 */
export default function ChatMessageBubble({ message }: { message: DisplayMessage }) {
  if (message.hidden) return null;

  const isUser = message.role === "user";
  const metadata = message.metadata;
  const isEmptyStreaming = message.isStreaming && !message.content;

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[85%] rounded-2xl px-3.5 py-2.5 text-sm leading-relaxed shadow-sm sm:max-w-[75%] ${
          isUser
            ? "bg-learner text-learner-fg"
            : "bg-tutor-soft/70 text-foreground ring-1 ring-tutor/15 dark:bg-tutor-soft/50"
        }`}
      >
        {!isUser ? (
          <p className="mb-1 text-[11px] font-medium text-tutor">Coach</p>
        ) : null}

        {isEmptyStreaming ? (
          <p className="text-sm text-muted">
            <span className="inline-flex items-center gap-1.5">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-tutor" />
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-tutor [animation-delay:120ms]" />
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-tutor [animation-delay:240ms]" />
              <span className="ml-1">Coach is thinking…</span>
            </span>
          </p>
        ) : isUser ? (
          <p className="whitespace-pre-wrap">
            {message.content}
          </p>
        ) : (
          <div className="chat-markdown">
            <Markdown remarkPlugins={[remarkGfm]} components={chatMarkdownComponents}>
              {message.content}
            </Markdown>
            {message.isStreaming ? (
              <span className="ml-0.5 inline-block h-3.5 w-1.5 animate-pulse bg-current align-middle opacity-70" />
            ) : null}
          </div>
        )}

        {!isUser && metadata?.corrections && metadata.corrections.length > 0 ? (
          <div className="mt-2.5 space-y-1.5 border-t border-border/60 pt-2">
            <p className="text-[10px] font-semibold uppercase tracking-wide text-warning">
              Corrections
            </p>
            <ul className="space-y-1">
              {metadata.corrections.map((correction, index) => (
                <li key={index} className="rounded-md bg-warning-soft/80 px-2 py-1 text-xs text-warning">
                  <span className="line-through opacity-70">{correction.span}</span>
                  {" → "}
                  <span className="font-medium">{correction.correction}</span>
                  {correction.note ? (
                    <span className="mt-0.5 block opacity-80">{correction.note}</span>
                  ) : null}
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {!isUser && metadata?.tips && metadata.tips.length > 0 ? (
          <div className="mt-2.5 space-y-1.5 border-t border-border/60 pt-2">
            <p className="text-[10px] font-semibold uppercase tracking-wide text-tutor">Tips</p>
            <ul className="space-y-1">
              {metadata.tips.map((tip, index) => (
                <li key={index} className="text-xs leading-snug text-muted">
                  {tip}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>
    </div>
  );
}
