"use client";

import { useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Components } from "react-markdown";

import type { ChatMessageMetadata } from "@/lib/chat";
import {
  buildThumbsEvent,
  canRateAssistantMessage,
  reportQualityEvent,
  type QualitySurface,
  type ThumbValue,
} from "@/lib/quality";

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

function StreamingDots() {
  return (
    <span className="inline-flex items-center gap-1" aria-label="Coach is typing">
      <span className="h-1 w-1 animate-pulse rounded-full bg-tutor" />
      <span className="h-1 w-1 animate-pulse rounded-full bg-tutor [animation-delay:120ms]" />
      <span className="h-1 w-1 animate-pulse rounded-full bg-tutor [animation-delay:240ms]" />
    </span>
  );
}

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

export interface ChatQualityContext {
  sessionId: string;
  surface: Extract<QualitySurface, "onboarding" | "lesson">;
  lessonId?: string | null;
  getToken: () => Promise<string | null>;
}

function ThumbIcon({ direction }: { direction: "up" | "down" }) {
  return (
    <svg
      viewBox="0 0 20 20"
      fill="currentColor"
      className={`h-3.5 w-3.5 ${direction === "down" ? "translate-y-px rotate-180" : ""}`}
      aria-hidden="true"
    >
      <path d="M10.75 2.75a.75.75 0 00-1.38-.36l-3.1 6.1A1.75 1.75 0 006 9.75V16c0 .97.78 1.75 1.75 1.75h6.17a2.25 2.25 0 002.2-1.76l.84-3.94A1.75 1.75 0 0015.04 10H12.5V4.5A1.75 1.75 0 0010.75 2.75zM4.5 9.75A.75.75 0 003.75 9h-.5A1.25 1.25 0 002 10.25v5.5C2 16.44 2.56 17 3.25 17h.5a.75.75 0 00.75-.75V9.75z" />
    </svg>
  );
}

function MessageThumbs({
  messageId,
  quality,
}: {
  messageId: string;
  quality: ChatQualityContext;
}) {
  const [selected, setSelected] = useState<ThumbValue | null>(null);

  const rate = (thumb: ThumbValue) => {
    if (selected !== null) return;
    setSelected(thumb);
    void (async () => {
      try {
        const token = await quality.getToken();
        reportQualityEvent(
          token,
          buildThumbsEvent({
            surface: quality.surface,
            sessionId: quality.sessionId,
            messageId,
            lessonId: quality.lessonId,
            thumb,
          })
        );
      } catch {
        // Fire-and-forget — selected state stays so the learner cannot spam.
      }
    })();
  };

  return (
    <div className="mt-1 flex items-center gap-0.5" role="group" aria-label="Rate this reply">
      {(
        [
          { thumb: 1 as const, label: "Helpful" },
          { thumb: -1 as const, label: "Not helpful" },
        ] as const
      ).map(({ thumb, label }) => {
        const isSelected = selected === thumb;
        const locked = selected !== null;
        return (
          <button
            key={thumb}
            type="button"
            aria-label={label}
            aria-pressed={isSelected}
            disabled={locked}
            title={label}
            onClick={() => rate(thumb)}
            className={`inline-flex h-7 w-7 items-center justify-center rounded-lg [transition:background-color_150ms_ease,color_150ms_ease,transform_120ms_cubic-bezier(0.23,1,0.32,1)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/20 ${
              isSelected
                ? "bg-tutor-soft text-tutor"
                : locked
                  ? "text-muted/40"
                  : "text-muted hover:bg-surface-muted hover:text-tutor active:scale-[0.97]"
            } disabled:cursor-default`}
          >
            <ThumbIcon direction={thumb === 1 ? "up" : "down"} />
          </button>
        );
      })}
    </div>
  );
}

/**
 * Shared chat bubble used by both onboarding and lesson chat. Tutor messages
 * get a soft teal accent + label; learner messages are right-aligned dark.
 * Corrections / tips from `done.metadata` render as a scannable brief under
 * the bubble. Thumbs appear only on persisted assistant turns (after SSE `done`).
 */
export default function ChatMessageBubble({
  message,
  quality,
}: {
  message: DisplayMessage;
  quality?: ChatQualityContext;
}) {
  if (message.hidden) return null;

  const isUser = message.role === "user";
  const metadata = message.metadata;
  const isEmptyStreaming = message.isStreaming && !message.content;
  const corrections = metadata?.corrections ?? [];
  const tips = metadata?.tips ?? [];
  const hasCorrections = corrections.length > 0;
  const hasTips = tips.length > 0;
  const showThumbs = Boolean(quality) && canRateAssistantMessage(message);

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div className={`flex flex-col ${isUser ? "max-w-[78%] items-end" : "max-w-[85%] items-start"}`}>
        {!isUser ? (
          <p className="mb-1 text-[11px] font-[550] leading-4 text-tutor">Coach</p>
        ) : null}

        <div
          className={`px-3.5 py-2.5 text-sm leading-[22px] ${
            isUser
              ? "rounded-[16px_4px_16px_16px] bg-learner text-learner-fg"
              : "rounded-[4px_16px_16px_16px] bg-tutor-soft text-tutor-fg"
          }`}
        >
          {isEmptyStreaming ? (
            <StreamingDots />
          ) : isUser ? (
            <p className="whitespace-pre-wrap">{message.content}</p>
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

          {!isUser && hasCorrections ? (
            <div className="mt-3 border-t border-border pt-2.5">
              <ul className="space-y-1.5">
                {corrections.map((correction, index) => (
                  <li key={index} className="text-[13px] leading-5">
                    <span className="text-muted line-through">{correction.span}</span>
                    {" → "}
                    <span className="font-semibold text-foreground">{correction.correction}</span>
                    {correction.note ? (
                      <span className="mt-0.5 block text-muted">{correction.note}</span>
                    ) : null}
                  </li>
                ))}
              </ul>
              {hasTips ? (
                <ul className="mt-2 space-y-1">
                  {tips.map((tip, index) => (
                    <li key={index} className="text-xs italic text-muted">
                      {tip}
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>
          ) : null}

          {!isUser && !hasCorrections && hasTips ? (
            <ul className="mt-2 space-y-1">
              {tips.map((tip, index) => (
                <li key={index} className="text-xs italic text-muted">
                  {tip}
                </li>
              ))}
            </ul>
          ) : null}
        </div>

        {showThumbs && quality ? <MessageThumbs messageId={message.id} quality={quality} /> : null}
      </div>
    </div>
  );
}
