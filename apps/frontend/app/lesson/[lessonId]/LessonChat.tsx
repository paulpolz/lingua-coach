"use client";

import { useAuth } from "@clerk/nextjs";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { createChatSession, getChatMessages, streamChatMessage, type ChatMessage } from "@/lib/chat";
import {
  describeFinishResult,
  finishLesson,
  stopLesson,
  writeFinishHint,
  type Lesson,
  type LessonCurriculum,
} from "@/lib/lessons";
import ChatMessageBubble, { type DisplayMessage } from "@/components/ChatMessageBubble";

interface LessonChatProps {
  lessonId: string;
  lesson: Lesson;
}

type LoadState = "loading" | "ready" | "error";

function sessionStorageKey(lessonId: string): string {
  return `lingua-coach:lesson-session-id:${lessonId}`;
}

function readStoredSessionId(lessonId: string): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.sessionStorage.getItem(sessionStorageKey(lessonId));
  } catch {
    return null;
  }
}

function writeStoredSessionId(lessonId: string, id: string): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.setItem(sessionStorageKey(lessonId), id);
  } catch {
    // sessionStorage unavailable (e.g. privacy mode) — in-memory state still works.
  }
}

/**
 * Lesson chat — the Phase 4 replacement for the Phase 3 placeholder body.
 * Mirrors OnboardingChat's session create/resume + SSE-streaming pattern
 * (see docs/implementation-readiness.md §6-8), adapted for lesson turns:
 * a collapsible lesson focus card instead of a full worksheet, and
 * Stop/Finish session controls instead of an Accept-plan card.
 */
export default function LessonChat({ lessonId, lesson }: LessonChatProps) {
  const { getToken } = useAuth();
  const router = useRouter();

  const curriculum = lesson.payload?.curriculum ?? null;

  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [loadError, setLoadError] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<DisplayMessage[]>([]);

  const [input, setInput] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  const [lastFailedContent, setLastFailedContent] = useState<string | null>(null);

  // Latest `suggest_finish` value from the most recent `done` event — drives
  // the (still-disabled) Finish lesson button's highlight. Lost on reload
  // since GET /chat/sessions/{id}/messages doesn't return metadata; that's
  // acceptable for MVP (the tutor re-signals it again once slots are done).
  const [suggestFinish, setSuggestFinish] = useState(false);
  const [isStopping, setIsStopping] = useState(false);
  const [focusCardOpen, setFocusCardOpen] = useState(true);
  const [isFinishing, setIsFinishing] = useState(false);
  const [finishError, setFinishError] = useState<string | null>(null);

  const scrollAnchorRef = useRef<HTMLDivElement | null>(null);
  const streamingMessageIdRef = useRef<string>("streaming-assistant");
  const hasAutoCollapsedRef = useRef(false);

  useEffect(() => {
    scrollAnchorRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages]);

  // Auto-collapse the focus card once the conversation gets going, so it
  // doesn't dominate the screen (frontend.md: "thin brief, not a
  // worksheet"). Still user-toggleable afterwards via the header.
  useEffect(() => {
    if (!hasAutoCollapsedRef.current && messages.length > 0) {
      hasAutoCollapsedRef.current = true;
      setFocusCardOpen(false);
    }
  }, [messages.length]);

  // Create-or-resume the lesson chat session, then load its transcript.
  useEffect(() => {
    let cancelled = false;

    async function init() {
      setLoadState("loading");
      setLoadError(null);
      try {
        const token = await getToken();
        let id = readStoredSessionId(lessonId);
        if (!id) {
          const session = await createChatSession(token, "lesson", lessonId);
          id = session.id;
          writeStoredSessionId(lessonId, id);
        }
        if (cancelled) return;
        setSessionId(id);

        const transcript = await getChatMessages(token, id);
        if (cancelled) return;
        setMessages(
          transcript.map((message: ChatMessage) => ({
            id: message.id,
            role: message.role,
            content: message.content,
          }))
        );
        setLoadState("ready");
      } catch (error) {
        if (cancelled) return;
        setLoadError(
          error instanceof Error
            ? error.message
            : "Could not reach the server. Is the backend running?"
        );
        setLoadState("error");
      }
    }

    init();
    return () => {
      cancelled = true;
    };
  }, [getToken, lessonId]);

  const retryInit = useCallback(() => {
    // Drop any stale/invalid cached session id and re-run the mount effect
    // by forcing a full reload — simplest reliable retry for this MVP page.
    if (typeof window !== "undefined") {
      window.location.reload();
    }
  }, []);

  const sendMessage = useCallback(
    async (content: string) => {
      if (!sessionId || isSending) return;

      setIsSending(true);
      setSendError(null);
      setLastFailedContent(null);

      const userMessage: DisplayMessage = {
        id: `local-user-${Date.now()}`,
        role: "user",
        content,
      };
      const streamingId = streamingMessageIdRef.current;
      setMessages((prev) => [
        ...prev,
        userMessage,
        { id: streamingId, role: "assistant", content: "", isStreaming: true },
      ]);

      const token = await getToken();

      await streamChatMessage(token, sessionId, content, {
        onToken: (text) => {
          setMessages((prev) =>
            prev.map((message) =>
              message.id === streamingId ? { ...message, content: message.content + text } : message
            )
          );
        },
        onDone: (data) => {
          setMessages((prev) =>
            prev.map((message) =>
              message.id === streamingId
                ? {
                    id: data.message_id,
                    role: "assistant",
                    content: data.content,
                    metadata: data.metadata,
                    isStreaming: false,
                  }
                : message
            )
          );
          // Track only the latest turn's signal — the tutor re-evaluates
          // this on every reply (readiness §7), so we don't latch `true`
          // forever once it's said once.
          setSuggestFinish(Boolean(data.metadata?.suggest_finish));
          setIsSending(false);
        },
        onError: (error) => {
          // Drop the empty streaming bubble and let the user retry the send.
          setMessages((prev) => prev.filter((message) => message.id !== streamingId));
          setSendError(error.message || "Something went wrong, try again.");
          setLastFailedContent(content);
          setIsSending(false);
        },
      });
    },
    [sessionId, isSending, getToken]
  );

  const submitInput = useCallback(() => {
    const content = input.trim();
    if (!content) return;
    setInput("");
    void sendMessage(content);
  }, [input, sendMessage]);

  const handleSubmit = useCallback(
    (event: React.FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      submitInput();
    },
    [submitInput]
  );

  const handleRetrySend = useCallback(() => {
    if (!lastFailedContent) return;
    void sendMessage(lastFailedContent);
  }, [lastFailedContent, sendMessage]);

  // "Stop session" is a UI-convenience action (backend.md): the lesson
  // stays active on the server either way, so we never block navigation on
  // this call — fire it, log failures non-blockingly, and leave immediately.
  const handleStop = useCallback(() => {
    if (isStopping) return;
    setIsStopping(true);
    void (async () => {
      try {
        const token = await getToken();
        await stopLesson(token, lessonId);
      } catch (error) {
        console.error("Failed to stop lesson session (non-blocking):", error);
      }
    })();
    router.push("/dashboard");
  }, [isStopping, getToken, lessonId, router]);

  // "Finish lesson" — always available while active (readiness §6, always
  // an explicit action even when `suggestFinish` is true). Nothing more to
  // do in this chat once accomplished, so we carry the one-line pace
  // acknowledgment across the redirect and hand off to the dashboard.
  const handleFinish = useCallback(() => {
    if (isFinishing) return;
    setIsFinishing(true);
    setFinishError(null);
    void (async () => {
      try {
        const token = await getToken();
        const result = await finishLesson(token, lessonId);
        writeFinishHint(describeFinishResult(result));
        router.push("/dashboard");
      } catch (error) {
        setFinishError(error instanceof Error ? error.message : "Failed to finish the lesson.");
        setIsFinishing(false);
      }
    })();
  }, [isFinishing, getToken, lessonId, router]);

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <LessonTopBar
        lessonNumber={lesson.lesson_number}
        curriculum={curriculum}
        focusCardOpen={focusCardOpen}
        onToggleFocusCard={() => setFocusCardOpen((open) => !open)}
        onStop={handleStop}
        isStopping={isStopping}
        suggestFinish={suggestFinish}
        onFinish={handleFinish}
        isFinishing={isFinishing}
        finishError={finishError}
        onDismissFinishError={() => setFinishError(null)}
      />

      {loadState === "loading" ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-3 p-6 text-center">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-zinc-300 border-t-zinc-600 dark:border-zinc-700 dark:border-t-zinc-300" />
          <p className="text-sm text-zinc-500">Opening lesson chat…</p>
        </div>
      ) : loadState === "error" ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-3 p-6 text-center">
          <p className="max-w-md text-sm text-red-600 dark:text-red-400">
            Could not load lesson chat. Is the backend running? ({loadError})
          </p>
          <button
            type="button"
            onClick={retryInit}
            className="rounded-lg border border-zinc-300 px-4 py-2 text-sm font-medium hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800"
          >
            Retry
          </button>
        </div>
      ) : (
        <>
          <div className="flex-1 overflow-y-auto px-3 pb-4 pt-4 sm:px-4">
            <div className="mx-auto flex w-full max-w-2xl flex-col gap-3">
              {messages.length === 0 ? (
                <p className="mt-8 text-center text-sm text-zinc-500">
                  {curriculum?.lesson_goal
                    ? `Say hello to start practicing: ${curriculum.lesson_goal}`
                    : "Say hello to start this lesson."}
                </p>
              ) : null}

              {messages.map((message) => (
                <ChatMessageBubble key={message.id} message={message} />
              ))}

              <div ref={scrollAnchorRef} />
            </div>
          </div>

          <div className="border-t border-zinc-200 bg-white/95 p-3 backdrop-blur sm:p-4 dark:border-zinc-800 dark:bg-zinc-950/95">
            <div className="mx-auto w-full max-w-2xl">
              {sendError ? (
                <div className="mb-2 flex items-center justify-between gap-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950/40 dark:text-red-300">
                  <span>{sendError}</span>
                  <button
                    type="button"
                    onClick={handleRetrySend}
                    className="shrink-0 font-medium underline underline-offset-2"
                  >
                    Retry
                  </button>
                </div>
              ) : null}
              <form onSubmit={handleSubmit} className="flex items-end gap-2">
                <textarea
                  value={input}
                  onChange={(event) => setInput(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" && !event.shiftKey) {
                      event.preventDefault();
                      submitInput();
                    }
                  }}
                  placeholder="Type your message…"
                  rows={1}
                  disabled={isSending}
                  className="flex-1 resize-none rounded-xl border border-zinc-300 bg-white px-3 py-2.5 text-sm outline-none focus:border-zinc-500 disabled:opacity-60 dark:border-zinc-700 dark:bg-zinc-900"
                />
                <button
                  type="submit"
                  disabled={isSending || !input.trim()}
                  className="shrink-0 rounded-xl bg-zinc-900 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-zinc-700 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-300"
                >
                  {isSending ? "…" : "Send"}
                </button>
              </form>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function LessonTopBar({
  lessonNumber,
  curriculum,
  focusCardOpen,
  onToggleFocusCard,
  onStop,
  isStopping,
  suggestFinish,
  onFinish,
  isFinishing,
  finishError,
  onDismissFinishError,
}: {
  lessonNumber: number;
  curriculum: LessonCurriculum | null;
  focusCardOpen: boolean;
  onToggleFocusCard: () => void;
  onStop: () => void;
  isStopping: boolean;
  suggestFinish: boolean;
  onFinish: () => void;
  isFinishing: boolean;
  finishError: string | null;
  onDismissFinishError: () => void;
}) {
  return (
    <div className="flex flex-col border-b border-zinc-200 dark:border-zinc-800">
      <div className="flex items-center justify-between gap-2 px-3 py-2.5 sm:px-4">
        <button
          type="button"
          onClick={onToggleFocusCard}
          className="flex min-w-0 flex-1 items-center gap-1.5 text-left"
          aria-expanded={focusCardOpen}
        >
          <span className="truncate text-sm font-semibold text-zinc-900 dark:text-zinc-100">
            Lesson {lessonNumber}
            {curriculum?.lesson_goal ? ` — ${curriculum.lesson_goal}` : ""}
          </span>
          <svg
            className={`h-3 w-3 shrink-0 text-zinc-400 transition-transform ${focusCardOpen ? "rotate-180" : ""}`}
            viewBox="0 0 20 20"
            fill="currentColor"
            aria-hidden="true"
          >
            <path
              fillRule="evenodd"
              d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z"
              clipRule="evenodd"
            />
          </svg>
        </button>

        <div className="flex shrink-0 items-center gap-2">
          <button
            type="button"
            onClick={onStop}
            disabled={isStopping}
            className="rounded-lg border border-zinc-300 px-2.5 py-1.5 text-xs font-medium text-zinc-700 transition hover:bg-zinc-100 disabled:cursor-not-allowed disabled:opacity-60 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-800"
          >
            {isStopping ? "Stopping…" : "Stop session"}
          </button>

          <button
            type="button"
            onClick={() => {
              if (window.confirm("Mark this lesson accomplished? Any unfinished slots count as 0%.")) {
                onFinish();
              }
            }}
            disabled={isFinishing}
            title={
              isFinishing
                ? "Finishing…"
                : suggestFinish
                  ? "Ready to finish! Marks the lesson accomplished and unlocks the next one."
                  : "Always available while the lesson is active."
            }
            className={`relative rounded-lg border px-2.5 py-1.5 text-xs font-medium transition disabled:cursor-not-allowed disabled:opacity-60 ${
              suggestFinish
                ? "animate-pulse border-emerald-400 bg-emerald-50 text-emerald-700 dark:border-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300"
                : "border-zinc-300 text-zinc-700 hover:bg-zinc-100 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-800"
            }`}
          >
            {isFinishing ? "Finishing…" : "Finish lesson"}
            {suggestFinish && !isFinishing ? (
              <span className="ml-1.5 rounded-full bg-emerald-600 px-1.5 py-0.5 text-[10px] font-semibold text-white">
                Ready!
              </span>
            ) : null}
          </button>
        </div>
      </div>

      {finishError ? (
        <div className="mx-3 mb-2 flex items-center justify-between gap-3 rounded-lg bg-red-50 px-3 py-2 text-xs text-red-700 sm:mx-4 dark:bg-red-950/40 dark:text-red-300">
          <span>{finishError}</span>
          <div className="flex shrink-0 items-center gap-2">
            <button type="button" onClick={onFinish} className="font-medium underline underline-offset-2">
              Retry
            </button>
            <button type="button" onClick={onDismissFinishError} className="font-medium underline underline-offset-2">
              Dismiss
            </button>
          </div>
        </div>
      ) : null}

      {focusCardOpen ? <LessonFocusCardBody curriculum={curriculum} /> : null}
    </div>
  );
}

function LessonFocusCardBody({ curriculum }: { curriculum: LessonCurriculum | null }) {
  if (!curriculum) {
    return (
      <p className="px-3 pb-3 text-xs text-zinc-500 sm:px-4">
        Curriculum details aren&apos;t available for this lesson yet.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-1 px-3 pb-3 text-xs text-zinc-600 sm:px-4 dark:text-zinc-400">
      {curriculum.grammar_focus ? (
        <p>
          <span className="font-medium text-zinc-700 dark:text-zinc-300">Grammar focus:</span>{" "}
          {curriculum.grammar_focus}
        </p>
      ) : null}
      {curriculum.vocab_theme ? (
        <p>
          <span className="font-medium text-zinc-700 dark:text-zinc-300">Vocab theme:</span>{" "}
          {curriculum.vocab_theme}
        </p>
      ) : null}
    </div>
  );
}
