"use client";

import { useCallback, useEffect, useRef, type FormEvent, type KeyboardEvent } from "react";

import Button from "@/components/ui/Button";

const MAX_TEXTAREA_PX = 180;

interface ChatComposerProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  disabled?: boolean;
  isSending?: boolean;
  placeholder?: string;
  /** When true, hide the send form (e.g. empty onboarding before Start). */
  hidden?: boolean;
  error?: string | null;
  onRetry?: () => void;
}

/**
 * Shared chat composer: auto-growing textarea (capped ~180px),
 * Enter to send, Shift+Enter for newline.
 */
export default function ChatComposer({
  value,
  onChange,
  onSubmit,
  disabled = false,
  isSending = false,
  placeholder = "Type your message…",
  hidden = false,
  error = null,
  onRetry,
}: ChatComposerProps) {
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  const resize = useCallback(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, MAX_TEXTAREA_PX)}px`;
  }, []);

  useEffect(() => {
    resize();
  }, [value, resize]);

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (disabled || isSending || !value.trim()) return;
    onSubmit();
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      if (disabled || isSending || !value.trim()) return;
      onSubmit();
    }
  };

  if (hidden) return null;

  return (
    <div className="border-t border-border bg-surface/95 p-3 backdrop-blur sm:p-4">
      <div className="mx-auto w-full max-w-2xl">
        {error ? (
          <div className="mb-2 flex items-center justify-between gap-3 rounded-lg bg-danger-soft px-3 py-2 text-sm text-danger">
            <span>{error}</span>
            {onRetry ? (
              <button
                type="button"
                onClick={onRetry}
                className="shrink-0 font-medium underline underline-offset-2"
              >
                Retry
              </button>
            ) : null}
          </div>
        ) : null}
        <form onSubmit={handleSubmit} className="flex items-end gap-2">
          <textarea
            ref={textareaRef}
            value={value}
            onChange={(event) => onChange(event.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={placeholder}
            rows={1}
            disabled={disabled || isSending}
            className="max-h-[180px] min-h-[44px] flex-1 resize-none overflow-y-auto rounded-xl border border-border-strong bg-surface px-3.5 py-2.5 text-sm leading-relaxed text-foreground outline-none transition focus:border-accent focus:ring-2 focus:ring-accent/20 disabled:opacity-60"
          />
          <Button
            type="submit"
            disabled={isSending || !value.trim()}
            className="shrink-0 min-w-[4.5rem]"
            aria-label={isSending ? "Sending" : "Send message"}
          >
            {isSending ? (
              <span className="inline-flex items-center gap-1">
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-current" />
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-current [animation-delay:120ms]" />
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-current [animation-delay:240ms]" />
              </span>
            ) : (
              "Send"
            )}
          </Button>
        </form>
        <p className="mt-1.5 text-[11px] text-muted">
          Enter to send · Shift+Enter for a new line
        </p>
      </div>
    </div>
  );
}
