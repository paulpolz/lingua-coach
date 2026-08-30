"use client";

import { useAuth } from "@clerk/nextjs";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { createChatSession, getChatMessages, streamChatMessage, type ChatMessage, type ChatMessageMetadata, type LessonPlanTask } from "@/lib/chat";
import { reportClientError } from "@/lib/reportError";
import {
  describeFinishResult,
  finishLesson,
  stopLesson,
  writeFinishHint,
  type FinishLessonRequest,
  type Lesson,
  type LessonCurriculum,
} from "@/lib/lessons";
import ChatComposer from "@/components/ChatComposer";
import ChatMessageBubble, { type DisplayMessage } from "@/components/ChatMessageBubble";
import FinishLessonDialog from "@/components/FinishLessonDialog";
import Button from "@/components/ui/Button";
import LessonChecklist from "./LessonChecklist";

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

function applyChecklistMetadata(
  metadata: ChatMessageMetadata | null | undefined,
  tasks: LessonPlanTask[],
  completedIds: Set<string>
): { tasks: LessonPlanTask[]; completedIds: Set<string> } {
  let nextTasks = tasks;
  const nextCompleted = new Set(completedIds);
  if (metadata?.lesson_plan?.tasks?.length) {
    nextTasks = metadata.lesson_plan.tasks;
    const ids = new Set(nextTasks.map((task) => task.id));
    for (const id of [...nextCompleted]) {
      if (!ids.has(id)) nextCompleted.delete(id);
    }
  }
  for (const id of metadata?.task_update?.completed_task_ids ?? []) {
    nextCompleted.add(id);
  }
  return { tasks: nextTasks, completedIds: nextCompleted };
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

  // Latest `suggest_finish` — restored from transcript metadata on reload
  // when available (GET /messages now returns metadata).
  const [suggestFinish, setSuggestFinish] = useState(false);
  const [checklistTasks, setChecklistTasks] = useState<LessonPlanTask[]>([]);
  const [completedTaskIds, setCompletedTaskIds] = useState<Set<string>>(() => new Set());
  const completedTaskIdsRef = useRef<Set<string>>(new Set());
  const [isStopping, setIsStopping] = useState(false);
  const [focusCardOpen, setFocusCardOpen] = useState(true);
  const [isFinishing, setIsFinishing] = useState(false);
  const [finishError, setFinishError] = useState<string | null>(null);
  const [finishDialogOpen, setFinishDialogOpen] = useState(false);
  const lastFinishPayloadRef = useRef<FinishLessonRequest>({});

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
            metadata: message.metadata ?? null,
          }))
        );
        let tasks: LessonPlanTask[] = [];
        let completed = new Set<string>();
        for (const message of transcript) {
          const next = applyChecklistMetadata(message.metadata, tasks, completed);
          tasks = next.tasks;
          completed = next.completedIds;
        }
        setChecklistTasks(tasks);
        completedTaskIdsRef.current = completed;
        setCompletedTaskIds(completed);
        // Restore the latest suggest_finish signal from transcript metadata.
        for (let i = transcript.length - 1; i >= 0; i--) {
          if (transcript[i].metadata?.suggest_finish) {
            setSuggestFinish(true);
            break;
          }
        }
        setLoadState("ready");
      } catch (error) {
        if (cancelled) return;
        setLoadError(
          error instanceof Error
            ? error.message
            : "Could not reach the server. Is the backend running?"
        );
        setLoadState("error");
        reportClientError({
          code: "LESSON_CHAT_LOAD_ERROR",
          message: error instanceof Error ? error.message : "Lesson chat load failed",
          surface: "lesson",
          meta: { lesson_id: lessonId },
        });
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
          setChecklistTasks((prevTasks) => {
            const next = applyChecklistMetadata(
              data.metadata,
              prevTasks,
              completedTaskIdsRef.current
            );
            completedTaskIdsRef.current = next.completedIds;
            setCompletedTaskIds(next.completedIds);
            return next.tasks;
          });
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
        reportClientError({
          code: "LESSON_STOP_ERROR",
          message: error instanceof Error ? error.message : "Failed to stop lesson",
          surface: "lesson",
          meta: { lesson_id: lessonId },
        });
      }
    })();
    router.push("/dashboard");
  }, [isStopping, getToken, lessonId, router]);

  // "Finish lesson" — always available while active (readiness §6, always
  // an explicit action even when `suggestFinish` is true). Nothing more to
  // do in this chat once accomplished, so we carry the one-line pace
  // acknowledgment across the redirect and hand off to the dashboard.
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
          const result = await finishLesson(token, lessonId, {
            ...feedback,
            completed_slot_ids: [...completedTaskIdsRef.current],
          });
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
        lessonNumber={lesson.lesson_number}
        curriculum={curriculum}
        focusCardOpen={focusCardOpen}
        onToggleFocusCard={() => setFocusCardOpen((open) => !open)}
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
            {checklistTasks.length > 0 ? (
              <div className="pointer-events-none absolute right-3 top-3 z-10">
                <div className="pointer-events-auto">
                  <LessonChecklist tasks={checklistTasks} completedIds={completedTaskIds} />
                </div>
              </div>
            ) : null}
            <div
              className={`h-full overflow-y-auto px-5 pb-5 pt-7 ${
                checklistTasks.length > 0 ? "md:mr-44" : ""
              }`}
            >
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
                    quality={
                      sessionId
                        ? { sessionId, surface: "lesson", lessonId, getToken }
                        : undefined
                    }
                  />
                ))}

                <div ref={scrollAnchorRef} />
              </div>
            </div>
          </div>

          {suggestFinish && checklistTasks.length > 0 ? (
            <div className="bg-background px-5 pt-2">
              <p className="mx-auto w-full max-w-[560px] text-xs text-muted [animation:enter-fade_180ms_ease-out]">
                {checklistTasks[checklistTasks.length - 1].label} is the last task. Finish from the
                bar when you are ready.
              </p>
            </div>
          ) : null}

          <ChatComposer
            value={input}
            onChange={setInput}
            onSubmit={submitInput}
            isSending={isSending}
            error={sendError}
            onRetry={handleRetrySend}
          />
        </>
      )}

      <FinishLessonDialog
        open={finishDialogOpen}
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
  onRetryFinish,
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
  onRetryFinish: () => void;
}) {
  const title = curriculum?.lesson_goal ? curriculum.lesson_goal : `Lesson ${lessonNumber}`;
  const focusParts = [
    curriculum?.grammar_focus ? `Grammar: ${curriculum.grammar_focus}` : null,
    curriculum?.vocab_theme ? `Vocab: ${curriculum.vocab_theme}` : null,
  ].filter(Boolean);

  return (
    <div className="flex flex-col border-b border-border bg-background">
      <div className="flex items-center justify-between gap-2 px-5 py-2">
        <button
          type="button"
          onClick={onToggleFocusCard}
          className="flex min-w-0 flex-1 items-center gap-1.5 text-left"
          aria-expanded={focusCardOpen}
        >
          <span className="truncate text-[13px] font-[550] leading-[18px] tracking-[-0.01em] text-foreground">
            {title}
          </span>
          <svg
            className={`h-3 w-3 shrink-0 text-muted transition-transform ${focusCardOpen ? "rotate-180" : ""}`}
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

      {focusCardOpen ? (
        <p className="px-5 pb-2 text-xs text-muted">
          {focusParts.length > 0
            ? focusParts.join(" · ")
            : "Curriculum details aren't available for this lesson yet."}
        </p>
      ) : null}

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
