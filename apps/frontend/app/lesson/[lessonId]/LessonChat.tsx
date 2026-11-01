"use client";

import { useAuth } from "@clerk/nextjs";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { isNotFoundError } from "@/lib/api";
import {
  createChatSession,
  getChatMessages,
  latestAssistantMetadata,
  type LessonTiming,
} from "@/lib/chat";
import {
  describeFinishResult,
  finishLesson,
  stopLesson,
  writeFinishHint,
  type FinishLessonRequest,
  type Lesson,
} from "@/lib/lessons";
import { useChatTurn } from "@/lib/use-chat-turn";
import ChatComposer from "@/components/ChatComposer";
import ChatMessageBubble from "@/components/ChatMessageBubble";
import FinishLessonDialog from "@/components/FinishLessonDialog";
import Button from "@/components/ui/Button";
import LessonTimeCard from "./LessonTimeCard";

const THREAD_CLASS = "mx-auto flex w-full max-w-[560px] flex-col gap-4";

export function BackToDashboardButton() {
  const router = useRouter();
  return (
    <Button variant="ghost" onClick={() => router.push("/dashboard")}>
      Back to dashboard
    </Button>
  );
}

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

function writeStoredSessionId(lessonId: string, id: string | null): void {
  if (typeof window === "undefined") return;
  try {
    if (id) window.sessionStorage.setItem(sessionStorageKey(lessonId), id);
    else window.sessionStorage.removeItem(sessionStorageKey(lessonId));
  } catch {
    // sessionStorage unavailable (e.g. privacy mode) — in-memory state still works.
  }
}

/**
 * Lesson chat: create/resume the lesson session, one JSON post per turn
 * (`useChatTurn`), a pinned time card, and Stop/Finish controls.
 */
export default function LessonChat({ lessonId, lesson }: LessonChatProps) {
  const { getToken } = useAuth();
  const router = useRouter();

  const curriculum = lesson.payload?.curriculum ?? null;

  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [loadError, setLoadError] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const { messages, setMessages, send, retry, isSending, sendError } = useChatTurn(sessionId);

  const [input, setInput] = useState("");
  const [isStopping, setIsStopping] = useState(false);
  const [isFinishing, setIsFinishing] = useState(false);
  const [finishError, setFinishError] = useState<string | null>(null);
  const [finishDialogOpen, setFinishDialogOpen] = useState(false);
  const lastFinishPayloadRef = useRef<FinishLessonRequest>({});

  const scrollAnchorRef = useRef<HTMLDivElement | null>(null);

  // Both come from the latest assistant turn, so a reload restores them from
  // the transcript. Older messages lack `timing`; before the first turn the
  // card starts at 0 of the lesson's target, when the payload has one.
  const suggestFinish = useMemo(() => {
    const latest = [...messages].reverse().find((m) => m.role === "assistant" && !m.isStreaming);
    return Boolean(latest?.metadata?.suggest_finish);
  }, [messages]);
  const timing = useMemo<LessonTiming | null>(() => {
    const fromTurn = latestAssistantMetadata(messages, "timing");
    if (fromTurn) return fromTurn;
    const target = lesson.payload?.target_minutes;
    return target ? { active_minutes: 0, target_minutes: target } : null;
  }, [messages, lesson.payload?.target_minutes]);

  useEffect(() => {
    scrollAnchorRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages]);

  // Create-or-resume the lesson chat session, then load its transcript.
  useEffect(() => {
    let cancelled = false;

    async function openSession(token: string | null): Promise<string> {
      const session = await createChatSession(token, "lesson", lessonId);
      writeStoredSessionId(lessonId, session.id);
      return session.id;
    }

    async function init() {
      setLoadState("loading");
      setLoadError(null);
      try {
        const token = await getToken();
        let id = readStoredSessionId(lessonId) ?? (await openSession(token));
        let transcript;
        try {
          transcript = await getChatMessages(token, id);
        } catch (error) {
          // A cached id that is gone or malformed (404 / 422): drop it and start over once.
          if (!isNotFoundError(error)) throw error;
          writeStoredSessionId(lessonId, null);
          id = await openSession(token);
          transcript = await getChatMessages(token, id);
        }
        if (cancelled) return;
        setSessionId(id);
        setMessages(transcript);
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
  }, [getToken, lessonId, setMessages]);

  const retryInit = useCallback(() => {
    // Re-run the mount effect by forcing a full reload — simplest reliable
    // retry for this MVP page.
    if (typeof window !== "undefined") {
      window.location.reload();
    }
  }, []);

  const submitInput = useCallback(() => {
    const content = input.trim();
    if (!content) return;
    setInput("");
    void send(content);
  }, [input, send]);

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

  // Finish is always an explicit action. The pace acknowledgment is carried
  // across the redirect to the dashboard.
  // CSAT / free-text are optional and must not block finish.
  const handleFinish = useCallback(
    (feedback: FinishLessonRequest = {}) => {
      if (isFinishing) return;
      lastFinishPayloadRef.current = feedback;
      setIsFinishing(true);
      setFinishError(null);
      void (async () => {
        try {
          const token = await getToken();
          const result = await finishLesson(token, lessonId, feedback);
          setFinishDialogOpen(false);
          writeFinishHint(describeFinishResult(result));
          router.push("/dashboard");
        } catch (error) {
          setFinishError(error instanceof Error ? error.message : "Failed to finish the lesson.");
          setIsFinishing(false);
        }
      })();
    },
    [isFinishing, getToken, lessonId, router]
  );

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <LessonTopBar
        title={curriculum?.lesson_goal || `Lesson ${lesson.lesson_number}`}
        onStop={handleStop}
        isStopping={isStopping}
        suggestFinish={suggestFinish}
        onFinish={() => setFinishDialogOpen(true)}
        isFinishing={isFinishing}
        finishError={finishError}
        onDismissFinishError={() => setFinishError(null)}
        onRetryFinish={() => handleFinish(lastFinishPayloadRef.current)}
      />

      {loadState === "loading" ? (
        <div className="flex flex-1 items-center justify-center p-6">
          <p className="text-sm text-muted">Loading…</p>
        </div>
      ) : loadState === "error" ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-3 p-6 text-center">
          <p className="max-w-md text-sm text-danger">
            Could not load lesson chat. Is the backend running? ({loadError})
          </p>
          <Button variant="ghost" onClick={retryInit}>
            Retry
          </Button>
        </div>
      ) : (
        <>
          <div className="relative flex-1 overflow-hidden">
            {timing ? (
              <div className="pointer-events-none absolute right-3 top-3 z-10">
                <LessonTimeCard timing={timing} />
              </div>
            ) : null}
            <div className={`h-full overflow-y-auto px-5 pb-5 pt-7 ${timing ? "md:mr-44" : ""}`}>
              <div className={THREAD_CLASS}>
                {messages.length === 0 ? (
                  <p className="mt-8 text-center text-sm text-muted">
                    {curriculum?.lesson_goal
                      ? `Say hello to start practicing: ${curriculum.lesson_goal}`
                      : "Say hello to start this lesson."}
                  </p>
                ) : null}

                {messages.map((message) => (
                  <ChatMessageBubble
                    key={message.id}
                    message={message}
                  />
                ))}

                <div ref={scrollAnchorRef} />
              </div>
            </div>
          </div>

          {suggestFinish ? (
            <div className="bg-background px-5 pt-2">
              <p className="mx-auto w-full max-w-[560px] text-xs text-muted [animation:enter-fade_180ms_ease-out]">
                That&apos;s today&apos;s practice time. Finish from the bar when you are ready.
              </p>
            </div>
          ) : null}

          <ChatComposer
            value={input}
            onChange={setInput}
            onSubmit={submitInput}
            isSending={isSending}
            error={sendError}
            onRetry={retry}
          />
        </>
      )}

      <FinishLessonDialog
        open={finishDialogOpen}
        timing={timing}
        isSubmitting={isFinishing}
        onCancel={() => {
          if (!isFinishing) setFinishDialogOpen(false);
        }}
        onConfirm={handleFinish}
      />
    </div>
  );
}

function LessonTopBar({
  title,
  onStop,
  isStopping,
  suggestFinish,
  onFinish,
  isFinishing,
  finishError,
  onDismissFinishError,
  onRetryFinish,
}: {
  title: string;
  onStop: () => void;
  isStopping: boolean;
  suggestFinish: boolean;
  onFinish: () => void;
  isFinishing: boolean;
  finishError: string | null;
  onDismissFinishError: () => void;
  onRetryFinish: () => void;
}) {
  return (
    <div className="flex flex-col border-b border-border bg-background">
      <div className="flex items-center justify-between gap-2 px-5 py-2">
        <span className="min-w-0 flex-1 truncate text-[13px] font-[550] leading-[18px] tracking-[-0.01em] text-foreground">
          {title}
        </span>

        <div className="flex shrink-0 items-center gap-2">
          <Button variant="ghost" size="sm" onClick={onStop} disabled={isStopping}>
            {isStopping ? "Stopping…" : "Stop session"}
          </Button>

          <Button
            variant={suggestFinish ? "primary" : "ghost"}
            size="sm"
            onClick={onFinish}
            disabled={isFinishing}
            title={
              isFinishing
                ? "Finishing…"
                : suggestFinish
                  ? "Ready to finish! Marks the lesson accomplished and unlocks the next one."
                  : "Always available while the lesson is active."
            }
          >
            {isFinishing ? "Finishing…" : "Finish lesson"}
          </Button>
        </div>
      </div>

      {finishError ? (
        <div className="flex items-center justify-between gap-3 bg-danger-soft px-5 py-2 text-[13px] text-danger">
          <span>{finishError}</span>
          <div className="flex shrink-0 items-center gap-1">
            <Button variant="ghost" size="sm" type="button" onClick={onRetryFinish}>
              Retry
            </Button>
            <Button variant="ghost" size="sm" type="button" onClick={onDismissFinishError}>
              Dismiss
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
