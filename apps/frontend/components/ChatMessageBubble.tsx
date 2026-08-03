"use client";

import type { ChatMessageMetadata } from "@/lib/chat";

/** A message rendered in a chat transcript — either persisted or still streaming in. */
export interface DisplayMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  metadata?: ChatMessageMetadata | null;
  /** Client-only, in-flight assistant reply — not yet finalized by a `done` event. */
  isStreaming?: boolean;
}

/**
 * Shared chat bubble used by both onboarding and lesson chat. Renders the
 * message text plus, for assistant turns, any `corrections` / `tips` from
 * `done.metadata` (readiness §8 shape) as a small annotated list under the
 * bubble — not a separate panel, per frontend.md's "thin brief" guidance.
 */
export default function ChatMessageBubble({ message }: { message: DisplayMessage }) {
  const isUser = message.role === "user";
  const metadata = message.metadata;

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[85%] rounded-2xl px-3.5 py-2.5 text-sm shadow-sm sm:max-w-[75%] ${
          isUser
            ? "bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900"
            : "bg-zinc-100 text-zinc-900 dark:bg-zinc-800 dark:text-zinc-100"
        }`}
      >
        <p className="whitespace-pre-wrap">
          {message.content}
          {message.isStreaming ? (
            <span className="ml-0.5 inline-block h-3.5 w-1.5 animate-pulse bg-current align-middle" />
          ) : null}
        </p>

        {!isUser && metadata?.corrections && metadata.corrections.length > 0 ? (
          <ul className="mt-2 space-y-1 border-t border-zinc-300/50 pt-2 dark:border-zinc-600/50">
            {metadata.corrections.map((correction, index) => (
              <li key={index} className="text-xs text-amber-700 dark:text-amber-400">
                <span className="line-through opacity-70">{correction.span}</span>
                {" → "}
                <span className="font-medium">{correction.correction}</span>
                {correction.note ? <span className="opacity-70"> ({correction.note})</span> : null}
              </li>
            ))}
          </ul>
        ) : null}

        {!isUser && metadata?.tips && metadata.tips.length > 0 ? (
          <ul className="mt-2 space-y-1 border-t border-zinc-300/50 pt-2 dark:border-zinc-600/50">
            {metadata.tips.map((tip, index) => (
              <li key={index} className="text-xs italic text-zinc-600 dark:text-zinc-400">
                💡 {tip}
              </li>
            ))}
          </ul>
        ) : null}
      </div>
    </div>
  );
}
