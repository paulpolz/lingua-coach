"use client";

import { useAuth } from "@clerk/nextjs";
import { useCallback, useState } from "react";

import { sendChatMessage, type DisplayMessage } from "@/lib/chat";
import { waitForToken } from "@/lib/wait-for-token";

const STREAMING_ID = "streaming-assistant";
const GENERIC_ERROR = "Something went wrong, try again.";

export interface SendOptions {
  /** Post the message without showing a learner bubble (silent onboarding triggers). */
  hidden?: boolean;
}

/**
 * One chat turn at a time for a session: owns the transcript, the in-flight
 * flag, the error line, and retry of the last failed message.
 *
 * A send shows the learner bubble and an empty coach bubble (typing dots)
 * right away; the stored reply replaces the coach bubble in one step. A failed
 * send removes the coach bubble and keeps the content (`lastFailed`) for `retry`.
 */
export function useChatTurn(sessionId: string | null, initialMessages: DisplayMessage[] = []) {
  const { getToken } = useAuth();
  const [messages, setMessages] = useState<DisplayMessage[]>(initialMessages);
  const [isSending, setIsSending] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  const [lastFailed, setLastFailed] = useState<{ content: string; options: SendOptions } | null>(null);

  /** Resolves `true` when the reply was stored and shown. */
  const send = useCallback(
    async (content: string, options: SendOptions = {}): Promise<boolean> => {
      if (!sessionId || isSending) return false;

      setIsSending(true);
      setSendError(null);
      setLastFailed(null);
      setMessages((prev) => [
        ...prev,
        { id: `local-user-${Date.now()}`, role: "user", content, hidden: options.hidden === true },
        { id: STREAMING_ID, role: "assistant", content: "", isStreaming: true },
      ]);

      const fail = (message: string) => {
        setMessages((prev) => prev.filter((item) => item.id !== STREAMING_ID));
        setSendError(message || GENERIC_ERROR);
        setLastFailed({ content, options });
        return false;
      };

      try {
        const token = await waitForToken(getToken);
        const data = await sendChatMessage(token, sessionId, content);
        if (!data.content?.trim()) return fail(GENERIC_ERROR);

        setMessages((prev) =>
          prev.map((item) =>
            item.id === STREAMING_ID
              ? { id: data.message_id, role: "assistant", content: data.content, metadata: data.metadata }
              : item
          )
        );
        return true;
      } catch (error) {
        return fail(error instanceof Error ? error.message : GENERIC_ERROR);
      } finally {
        setIsSending(false);
      }
    },
    [sessionId, isSending, getToken]
  );

  const retry = useCallback(() => {
    if (!lastFailed) return;
    void send(lastFailed.content, lastFailed.options);
  }, [lastFailed, send]);

  return { messages, setMessages, send, retry, lastFailed, isSending, sendError };
}
