"use client";

import { useAuth } from "@clerk/nextjs";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { syncUser } from "@/lib/api";
import { waitForToken } from "@/lib/wait-for-token";
import {
  acceptOnboarding,
  createChatSession,
  getChatMessages,
  streamChatMessage,
  type ChatMessage,
  type CourseRoadmap,
} from "@/lib/chat";
import ChatComposer from "@/components/ChatComposer";
import ChatMessageBubble, { type DisplayMessage } from "@/components/ChatMessageBubble";
import Button from "@/components/ui/Button";
import PlanSummaryCard from "./PlanSummaryCard";

const SESSION_STORAGE_KEY = "lingua-coach:onboarding-session-id";
const DISMISSED_PLANS_KEY = "lingua-coach:dismissed-plan-ids";
const START_TRIGGER = "Hello";
const CHANGE_PLAN_PROMPT =
  "What would you like to change in your plan? You can adjust milestones, pace, topics, or weekly balance.";

type LoadState = "loading" | "ready" | "error";

type PlanStatus = "active" | "dismissed" | "superseded";

type ChatTimelineItem =
  | ({ kind: "message"; isPlanStream?: boolean } & DisplayMessage)
  | {
      kind: "plan";
      id: string;
      sourceMessageId: string;
      roadmap: CourseRoadmap;
      status: PlanStatus;
    };

/** Detect when the model is streaming a course roadmap (markdown or JSON fence). */
function isPlanStreamContent(content: string): boolean {
  if (/# Your course roadmap/i.test(content)) return true;
  if (/```json:course_roadmap/.test(content)) return true;
  if (/## Milestones/i.test(content)) return true;
  if (/course roadmap|personalized (?:learning )?plan/i.test(content)) return true;
  if (
    /Here(?:'s| is) (?:your|the updated)/i.test(content) &&
    /roadmap|plan/i.test(content)
  ) {
    return true;
  }
  return false;
}

function timelineHasPriorPlan(items: ChatTimelineItem[]): boolean {
  return items.some(
    (item) =>
      item.kind === "plan" ||
      (item.kind === "message" &&
        item.role === "assistant" &&
        Boolean(item.metadata?.course_roadmap_draft))
  );
}

function PlanGeneratingPlaceholder() {
  return (
    <div className="w-full rounded-2xl border border-border bg-surface p-4 shadow-sm sm:p-5">
      <div className="flex items-center gap-3">
        <div className="h-5 w-5 animate-spin rounded-full border-2 border-border border-t-tutor" />
        <p className="text-sm text-muted">Building your proposed plan…</p>
      </div>
    </div>
  );
}

function clearStoredSessionId(): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.removeItem(SESSION_STORAGE_KEY);
  } catch {
    // sessionStorage unavailable — nothing to clear.
  }
}

function readStoredSessionId(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.sessionStorage.getItem(SESSION_STORAGE_KEY);
  } catch {
    return null;
  }
}

function writeStoredSessionId(id: string): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.setItem(SESSION_STORAGE_KEY, id);
  } catch {
    // sessionStorage unavailable — in-memory state still works.
  }
}

function readDismissedPlanIds(): Set<string> {
  if (typeof window === "undefined") return new Set();
  try {
    const raw = window.sessionStorage.getItem(DISMISSED_PLANS_KEY);
    if (!raw) return new Set();
    const parsed = JSON.parse(raw) as unknown;
    return Array.isArray(parsed) ? new Set(parsed.filter((x): x is string => typeof x === "string")) : new Set();
  } catch {
    return new Set();
  }
}

function writeDismissedPlanIds(ids: Set<string>): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.setItem(DISMISSED_PLANS_KEY, JSON.stringify([...ids]));
  } catch {
    // ignore
  }
}

function buildTimelineFromTranscript(messages: ChatMessage[]): ChatTimelineItem[] {
  const dismissed = readDismissedPlanIds();
  const items: ChatTimelineItem[] = [];
  let lastActivePlanId: string | null = null;

  for (let index = 0; index < messages.length; index++) {
    const message = messages[index];
    // Hide the silent Start trigger ("Hello") so reload doesn't show a fake user bubble.
    const isSilentStart =
      index === 0 &&
      message.role === "user" &&
      message.content.trim().toLowerCase() === START_TRIGGER.toLowerCase();

    items.push({
      kind: "message",
      id: message.id,
      role: message.role,
      content: message.content,
      metadata: message.metadata ?? null,
      hidden: isSilentStart,
    });

    const draft = message.metadata?.course_roadmap_draft;
    if (message.role === "assistant" && draft) {
      const planId = `plan-${message.id}`;
      if (lastActivePlanId) {
        const prior = items.find((item) => item.kind === "plan" && item.id === lastActivePlanId);
        if (prior && prior.kind === "plan" && prior.status === "active") {
          prior.status = "superseded";
        }
      }
      const status: PlanStatus = dismissed.has(planId) ? "dismissed" : "active";
      items.push({
        kind: "plan",
        id: planId,
        sourceMessageId: message.id,
        roadmap: draft,
        status,
      });
      if (status === "active") {
        lastActivePlanId = planId;
      }
    }
  }

  // Only the latest non-dismissed plan should be active.
  let seenActive = false;
  for (let i = items.length - 1; i >= 0; i--) {
    const item = items[i];
    if (item.kind !== "plan") continue;
    if (item.status === "dismissed" || item.status === "superseded") continue;
    if (!seenActive) {
      seenActive = true;
    } else {
      item.status = "superseded";
    }
  }

  return items;
}

export default function OnboardingChat() {
  const { getToken } = useAuth();
  const router = useRouter();

  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [loadError, setLoadError] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [timeline, setTimeline] = useState<ChatTimelineItem[]>([]);

  const [input, setInput] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  const [lastFailedContent, setLastFailedContent] = useState<string | null>(null);
  const [lastFailedSilent, setLastFailedSilent] = useState(false);

  const [isAccepting, setIsAccepting] = useState(false);
  const [acceptError, setAcceptError] = useState<string | null>(null);
  const [hasStarted, setHasStarted] = useState(false);

  const scrollAnchorRef = useRef<HTMLDivElement | null>(null);
  const streamingMessageIdRef = useRef<string>("streaming-assistant");

  const visibleMessageCount = useMemo(
    () => timeline.filter((item) => item.kind === "message" && !item.hidden).length,
    [timeline]
  );

  const activePlan = useMemo(
    () => timeline.find((item): item is Extract<ChatTimelineItem, { kind: "plan" }> => item.kind === "plan" && item.status === "active") ?? null,
    [timeline]
  );

  const showIntro = loadState === "ready" && visibleMessageCount === 0 && !hasStarted && !isSending;

  useEffect(() => {
    scrollAnchorRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [timeline]);

  useEffect(() => {
    let cancelled = false;

    async function init() {
      setLoadState("loading");
      setLoadError(null);
      try {
        const token = await waitForToken(getToken);
        await syncUser(token);

        let id = readStoredSessionId();
        if (!id) {
          const session = await createChatSession(token, "onboarding");
          id = session.id;
          writeStoredSessionId(id);
        }
        if (cancelled) return;
        setSessionId(id);

        const transcript = await getChatMessages(token, id);
        if (cancelled) return;
        const built = buildTimelineFromTranscript(transcript);
        setTimeline(built);
        if (transcript.length > 0) {
          setHasStarted(true);
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
      }
    }

    init();
    return () => {
      cancelled = true;
    };
  }, [getToken]);

  const retryInit = useCallback(() => {
    clearStoredSessionId();
    if (typeof window !== "undefined") {
      window.location.reload();
    }
  }, []);

  const sendMessage = useCallback(
    async (content: string, options?: { silent?: boolean }) => {
      if (!sessionId || isSending) return;
      const silent = options?.silent === true;

      setIsSending(true);
      setSendError(null);
      setLastFailedContent(null);
      setLastFailedSilent(false);
      setHasStarted(true);

      const userMessage: DisplayMessage & { kind: "message" } = {
        kind: "message",
        id: `local-user-${Date.now()}`,
        role: "user",
        content,
        hidden: silent,
      };
      const streamingId = streamingMessageIdRef.current;
      setTimeline((prev) => [
        ...prev,
        userMessage,
        {
          kind: "message",
          id: streamingId,
          role: "assistant",
          content: "",
          isStreaming: true,
          isPlanStream: timelineHasPriorPlan(prev),
        },
      ]);

      const token = await getToken();

      await streamChatMessage(token, sessionId, content, {
        onToken: (text) => {
          setTimeline((prev) =>
            prev.map((item) => {
              if (item.kind !== "message" || item.id !== streamingId) return item;
              const content = item.content + text;
              const looksLikeQuestion =
                content.includes("?") && content.length < 400;
              const isPlanStream =
                item.isPlanStream ||
                isPlanStreamContent(content) ||
                (content.length >= 180 && !looksLikeQuestion);
              return {
                ...item,
                content,
                isPlanStream,
              };
            })
          );
        },
        onDone: (data) => {
          setTimeline((prev) => {
            const next = prev.map((item) => {
              if (item.kind === "message" && item.id === streamingId) {
                return {
                  kind: "message" as const,
                  id: data.message_id,
                  role: "assistant" as const,
                  content: data.content,
                  metadata: data.metadata,
                  isStreaming: false,
                };
              }
              if (
                item.kind === "plan" &&
                item.status === "active" &&
                data.metadata?.course_roadmap_draft
              ) {
                return { ...item, status: "superseded" as const };
              }
              return item;
            });

            if (data.metadata?.course_roadmap_draft) {
              next.push({
                kind: "plan",
                id: `plan-${data.message_id}`,
                sourceMessageId: data.message_id,
                roadmap: data.metadata.course_roadmap_draft,
                status: "active",
              });
            }
            return next;
          });
          setIsSending(false);
        },
        onError: (error) => {
          setTimeline((prev) =>
            prev.filter((item) => !(item.kind === "message" && item.id === streamingId))
          );
          setSendError(error.message || "Something went wrong, try again.");
          setLastFailedContent(content);
          setLastFailedSilent(silent);
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
    void sendMessage(lastFailedContent, { silent: lastFailedSilent });
  }, [lastFailedContent, lastFailedSilent, sendMessage]);

  const handleStart = useCallback(() => {
    void sendMessage(START_TRIGGER, { silent: true });
  }, [sendMessage]);

  const handleAccept = useCallback(async () => {
    if (!sessionId || !activePlan) return;
    setIsAccepting(true);
    setAcceptError(null);
    try {
      const token = await getToken();
      const result = await acceptOnboarding(token, sessionId, activePlan.roadmap);
      if (result.onboarding_complete) {
        router.push("/dashboard");
        return;
      }
      setAcceptError("The server didn't confirm the plan was accepted. Please try again.");
    } catch (error) {
      setAcceptError(error instanceof Error ? error.message : "Failed to accept the plan.");
    } finally {
      setIsAccepting(false);
    }
  }, [sessionId, activePlan, getToken, router]);

  const handleChangePlan = useCallback(() => {
    if (!activePlan) return;
    const dismissed = readDismissedPlanIds();
    dismissed.add(activePlan.id);
    writeDismissedPlanIds(dismissed);
    setTimeline((prev) => [
      ...prev.map((item) =>
        item.kind === "plan" && item.id === activePlan.id
          ? { ...item, status: "dismissed" as const }
          : item
      ),
      {
        kind: "message",
        id: `local-change-prompt-${Date.now()}`,
        role: "assistant",
        content: CHANGE_PLAN_PROMPT,
      },
    ]);
    setAcceptError(null);
    requestAnimationFrame(() => {
      const el = document.querySelector<HTMLTextAreaElement>(
        "textarea[placeholder='Type your message…']"
      );
      el?.focus();
    });
  }, [activePlan]);

  if (loadState === "loading") {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-3 p-6 text-center">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-border border-t-tutor" />
        <p className="text-sm text-muted">Starting your onboarding chat…</p>
      </div>
    );
  }

  if (loadState === "error") {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-3 p-6 text-center">
        <p className="max-w-md text-sm text-danger">
          Could not load onboarding chat. Is the backend running? ({loadError})
        </p>
        <Button variant="secondary" onClick={retryInit}>
          Retry
        </Button>
      </div>
    );
  }

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <div className="flex-1 overflow-y-auto px-3 pb-4 pt-4 sm:px-4">
        <div className="mx-auto flex w-full max-w-2xl flex-col gap-3">
          {showIntro ? (
            <div className="mx-auto mt-6 max-w-md rounded-2xl border border-border bg-surface p-6 text-center shadow-sm">
              <h2 className="text-lg font-semibold text-foreground">
                Let&apos;s build your learning plan
              </h2>
              <p className="mt-2 text-sm leading-relaxed text-muted">
                We&apos;ll ask you a few quick questions about your goals and English level to build
                your personalized learning plan. Takes about 2 minutes.
              </p>
              <Button onClick={handleStart} disabled={isSending} className="mt-5 w-full sm:w-auto">
                {isSending ? "Starting…" : "Start"}
              </Button>
            </div>
          ) : null}

          {timeline.map((item) => {
            if (item.kind === "message") {
              const hideForPlanDraft =
                item.role === "assistant" && Boolean(item.metadata?.course_roadmap_draft);
              if (hideForPlanDraft) return null;

              const streamingPlan =
                item.isStreaming &&
                item.role === "assistant" &&
                (item.isPlanStream ||
                  isPlanStreamContent(item.content) ||
                  (item.content.length >= 120 && !item.content.includes("?")));

              if (streamingPlan) {
                return <PlanGeneratingPlaceholder key={item.id} />;
              }

              return <ChatMessageBubble key={item.id} message={item} />;
            }
            if (item.status !== "active") return null;
            return (
              <PlanSummaryCard
                key={item.id}
                roadmap={item.roadmap}
                onAccept={handleAccept}
                onChange={handleChangePlan}
                isAccepting={isAccepting}
                acceptError={acceptError}
              />
            );
          })}

          <div ref={scrollAnchorRef} />
        </div>
      </div>

      <ChatComposer
        value={input}
        onChange={setInput}
        onSubmit={submitInput}
        isSending={isSending}
        hidden={showIntro}
        error={sendError}
        onRetry={handleRetrySend}
      />
    </div>
  );
}
