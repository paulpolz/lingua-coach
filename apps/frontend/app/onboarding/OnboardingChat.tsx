"use client";

import { useAuth } from "@clerk/nextjs";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { waitForToken } from "@/lib/wait-for-token";
import {
  acceptOnboarding,
  type ChatMessage,
  type CourseRoadmap,
  type DisplayMessage,
} from "@/lib/chat";
import { isTimeBudgetRequired } from "@/lib/lessons";
import { useChatTurn } from "@/lib/use-chat-turn";
import ChatComposer from "@/components/ChatComposer";
import ChatMessageBubble from "@/components/ChatMessageBubble";
import Button from "@/components/ui/Button";
import PlanSummaryCard from "./PlanSummaryCard";

const START_TRIGGER = "Hello";
const CHANGE_PLAN_TRIGGER = "I'd like to change my plan.";

interface OnboardingChatProps {
  initialSessionId: string;
  initialMessages: ChatMessage[];
}

interface ActivePlan {
  sourceMessageId: string;
  roadmap: CourseRoadmap;
}

const THREAD_CLASS = "mx-auto flex w-full max-w-[560px] flex-col gap-4";

function isTrigger(content: string, trigger: string): boolean {
  return content.trim().toLowerCase() === trigger.toLowerCase();
}

/** Hide the silent Start / Change-plan triggers so a reload doesn't show a fake user bubble. */
function toDisplayMessages(messages: ChatMessage[]): DisplayMessage[] {
  return messages.map((message, index) => ({
    id: message.id,
    role: message.role,
    content: message.content,
    metadata: message.metadata ?? null,
    hidden:
      message.role === "user" &&
      ((index === 0 && isTrigger(message.content, START_TRIGGER)) ||
        isTrigger(message.content, CHANGE_PLAN_TRIGGER)),
  }));
}

/** The latest `course_roadmap_draft` is the active plan; earlier drafts are superseded. */
function findActivePlan(messages: DisplayMessage[]): ActivePlan | null {
  for (let i = messages.length - 1; i >= 0; i--) {
    const message = messages[i];
    const draft = message.role === "assistant" ? message.metadata?.course_roadmap_draft : null;
    if (draft) return { sourceMessageId: message.id, roadmap: draft };
  }
  return null;
}

export default function OnboardingChat({
  initialSessionId,
  initialMessages,
}: OnboardingChatProps) {
  const { getToken } = useAuth();
  const router = useRouter();

  const sessionId = initialSessionId;
  const { messages, send, lastFailed, isSending, sendError } = useChatTurn(
    sessionId,
    toDisplayMessages(initialMessages)
  );

  const [input, setInput] = useState("");
  const [isPlanRegenerating, setIsPlanRegenerating] = useState(false);

  const [isAccepting, setIsAccepting] = useState(false);
  const [acceptError, setAcceptError] = useState<string | null>(null);
  const [hasStarted, setHasStarted] = useState(() => initialMessages.length > 0);
  const [justUpdated, setJustUpdated] = useState(false);

  const scrollAnchorRef = useRef<HTMLDivElement | null>(null);
  const prevPlanSourceIdRef = useRef<string | null>(null);

  const visibleMessageCount = useMemo(
    () => messages.filter((message) => !message.hidden).length,
    [messages]
  );

  const activePlan = useMemo(() => findActivePlan(messages), [messages]);

  const showIntro = visibleMessageCount === 0 && !hasStarted && !isSending;

  useEffect(() => {
    scrollAnchorRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages]);

  useEffect(() => {
    const sourceId = activePlan?.sourceMessageId ?? null;
    if (!sourceId) {
      prevPlanSourceIdRef.current = null;
      return;
    }
    if (prevPlanSourceIdRef.current && prevPlanSourceIdRef.current !== sourceId) {
      setJustUpdated(true);
      const timeout = window.setTimeout(() => setJustUpdated(false), 2000);
      prevPlanSourceIdRef.current = sourceId;
      return () => window.clearTimeout(timeout);
    }
    prevPlanSourceIdRef.current = sourceId;
    setJustUpdated(false);
  }, [activePlan?.sourceMessageId]);

  const sendMessage = useCallback(
    async (content: string, options?: { silent?: boolean }) => {
      if (isSending) return;
      const silent = options?.silent === true;
      setHasStarted(true);
      setIsPlanRegenerating(silent && isTrigger(content, CHANGE_PLAN_TRIGGER));
      try {
        await send(content, { hidden: silent });
      } finally {
        setIsPlanRegenerating(false);
      }
    },
    [isSending, send]
  );

  const submitInput = useCallback(() => {
    const content = input.trim();
    if (!content) return;
    setInput("");
    void sendMessage(content);
  }, [input, sendMessage]);

  // Retry through `sendMessage` so a failed silent Change still shows the regenerating overlay.
  const handleRetrySend = useCallback(() => {
    if (!lastFailed) return;
    void sendMessage(lastFailed.content, { silent: lastFailed.options.hidden });
  }, [lastFailed, sendMessage]);

  const handleStart = useCallback(() => {
    void sendMessage(START_TRIGGER, { silent: true });
  }, [sendMessage]);

  const handleAccept = useCallback(async () => {
    if (!sessionId || !activePlan) return;
    setIsAccepting(true);
    setAcceptError(null);
    try {
      const token = await waitForToken(getToken);
      const result = await acceptOnboarding(token, sessionId, activePlan.roadmap);
      if (result.onboarding_complete) {
        router.push("/dashboard");
        return;
      }
      setAcceptError("The server didn't confirm the plan was accepted. Please try again.");
    } catch (error) {
      setAcceptError(
        isTimeBudgetRequired(error)
          ? "Tell the coach how many minutes each lesson should last, then accept the updated plan."
          : error instanceof Error
            ? error.message
            : "Failed to accept the plan."
      );
    } finally {
      setIsAccepting(false);
    }
  }, [sessionId, activePlan, getToken, router]);

  const handleChangePlan = useCallback(() => {
    if (!activePlan || isSending) return;
    setAcceptError(null);
    void sendMessage(CHANGE_PLAN_TRIGGER, { silent: true });
  }, [activePlan, isSending, sendMessage]);

  const chatMessages = (
    <>
      {showIntro ? (
        <div className="mx-auto mt-6 max-w-[400px] text-center">
          <h2 className="text-[22px] font-[590] leading-7 tracking-[-0.03em] text-foreground">
            Let&apos;s build your learning plan
          </h2>
          <p className="mx-auto mt-2 max-w-[34ch] text-sm leading-[22px] text-muted">
            We&apos;ll ask about your native language, the language you want to learn, then your
            goals and level. Takes about 2 minutes.
          </p>
          <Button onClick={handleStart} disabled={isSending} className="mt-5">
            {isSending ? "Starting…" : "Start"}
          </Button>
        </div>
      ) : null}

      {messages.map((message) => {
        const hideForPlanDraft =
          message.role === "assistant" && Boolean(message.metadata?.course_roadmap_draft);
        if (hideForPlanDraft) return null;
        return <ChatMessageBubble key={message.id} message={message} />;
      })}

      <div ref={scrollAnchorRef} />
    </>
  );

  const composer = (
    <ChatComposer
      value={input}
      onChange={setInput}
      onSubmit={submitInput}
      isSending={isSending}
      hidden={showIntro}
      error={sendError}
      onRetry={handleRetrySend}
    />
  );

  if (activePlan) {
    return (
      <div className="flex flex-1 flex-col overflow-hidden md:flex-row">
        <aside className="flex max-h-[45vh] w-full shrink-0 flex-col overflow-hidden border-b border-border bg-background px-5 py-5 md:max-h-none md:w-[36%] md:min-w-[280px] md:max-w-[400px] md:border-b-0 md:border-r md:pb-6">
          <PlanSummaryCard
            roadmap={activePlan.roadmap}
            onAccept={handleAccept}
            onChange={handleChangePlan}
            isAccepting={isAccepting}
            isBusy={isSending}
            isRegenerating={isPlanRegenerating}
            justUpdated={justUpdated}
            acceptError={acceptError}
          />
        </aside>
        <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
          <div className="flex-1 overflow-y-auto px-5 pb-5 pt-7">
            <div className={THREAD_CLASS}>{chatMessages}</div>
          </div>
          {composer}
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <div className="flex-1 overflow-y-auto px-5 pb-5 pt-7">
        <div className={THREAD_CLASS}>{chatMessages}</div>
      </div>
      {composer}
    </div>
  );
}
