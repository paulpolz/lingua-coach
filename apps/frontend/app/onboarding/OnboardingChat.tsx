"use client";

import { useAuth } from "@clerk/nextjs";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { syncUser } from "@/lib/api";
import {
  acceptOnboarding,
  createChatSession,
  getChatMessages,
  streamChatMessage,
  type ChatMessage,
  type CourseRoadmap,
} from "@/lib/chat";
import ChatMessageBubble, { type DisplayMessage } from "@/components/ChatMessageBubble";
import PlanSummaryCard from "./PlanSummaryCard";

const SESSION_STORAGE_KEY = "lingua-coach:onboarding-session-id";

type LoadState = "loading" | "ready" | "error";

function clearStoredSessionId(): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.removeItem(SESSION_STORAGE_KEY);
  } catch {
    // sessionStorage unavailable — nothing to clear.
  }
}

function writeStoredSessionId(id: string): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.setItem(SESSION_STORAGE_KEY, id);
  } catch {
    // sessionStorage unavailable (e.g. privacy mode) — in-memory state still works.
  }
}

export default function OnboardingChat() {
  const { getToken } = useAuth();
  const router = useRouter();

  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [loadError, setLoadError] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [draftRoadmap, setDraftRoadmap] = useState<CourseRoadmap | null>(null);

  const [input, setInput] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  const [lastFailedContent, setLastFailedContent] = useState<string | null>(null);

  const [isAccepting, setIsAccepting] = useState(false);
  const [acceptError, setAcceptError] = useState<string | null>(null);

  const scrollAnchorRef = useRef<HTMLDivElement | null>(null);
  const streamingMessageIdRef = useRef<string>("streaming-assistant");

  useEffect(() => {
    scrollAnchorRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages]);

  // Create-or-resume the onboarding chat session, then load its transcript.
  useEffect(() => {
    let cancelled = false;

    async function init() {
      setLoadState("loading");
      setLoadError(null);
      try {
        const token = await getToken();
        // Ensure the Postgres user row exists even when /onboarding is opened
        // directly (bypassing `/`, which normally calls sync).
        await syncUser(token);

        // Always create-or-resume via the backend — it returns this user's
        // canonical onboarding session. A cached sessionStorage id may belong
        // to a previous Clerk account in the same browser tab.
        const session = await createChatSession(token, "onboarding");
        const id = session.id;
        writeStoredSessionId(id);
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
  }, [getToken]);

  const retryInit = useCallback(() => {
    // Drop any stale/invalid cached session id and re-run the mount effect
    // by forcing a full reload — simplest reliable retry for this MVP page.
    clearStoredSessionId();
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

      // Optimistically render the user's message; the transcript is still
      // re-fetchable from the backend on reload, so this is display-only.
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
          if (data.metadata?.course_roadmap_draft) {
            setDraftRoadmap(data.metadata.course_roadmap_draft);
          }
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

  const handleAccept = useCallback(async () => {
    if (!sessionId || !draftRoadmap) return;
    setIsAccepting(true);
    setAcceptError(null);
    try {
      const token = await getToken();
      const result = await acceptOnboarding(token, sessionId, draftRoadmap);
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
  }, [sessionId, draftRoadmap, getToken, router]);

  if (loadState === "loading") {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-3 p-6 text-center">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-zinc-300 border-t-zinc-600 dark:border-zinc-700 dark:border-t-zinc-300" />
        <p className="text-sm text-zinc-500">Starting your onboarding chat…</p>
      </div>
    );
  }

  if (loadState === "error") {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-3 p-6 text-center">
        <p className="max-w-md text-sm text-red-600 dark:text-red-400">
          Could not load onboarding chat. Is the backend running? ({loadError})
        </p>
        <button
          type="button"
          onClick={retryInit}
          className="rounded-lg border border-zinc-300 px-4 py-2 text-sm font-medium hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800"
        >
          Retry
        </button>
      </div>
    );
  }

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <div className="flex-1 overflow-y-auto px-3 pb-4 pt-4 sm:px-4">
        <div className="mx-auto flex w-full max-w-2xl flex-col gap-3">
          {messages.length === 0 ? (
            <p className="mt-8 text-center text-sm text-zinc-500">
              Say hello to start your onboarding interview.
            </p>
          ) : null}

          {messages.map((message) => (
            <ChatMessageBubble key={message.id} message={message} />
          ))}

          {draftRoadmap ? (
            <PlanSummaryCard
              roadmap={draftRoadmap}
              onAccept={handleAccept}
              isAccepting={isAccepting}
              acceptError={acceptError}
            />
          ) : null}

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
    </div>
  );
}
