import { afterEach, describe, expect, it, vi } from "vitest";

import {
  buildThumbsEvent,
  canRateAssistantMessage,
  isCsatValue,
  isPersistedMessageId,
  submitQualityEvent,
} from "./quality";

const REAL_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee";

describe("isPersistedMessageId", () => {
  it("accepts a real UUID from SSE done / GET transcript", () => {
    expect(isPersistedMessageId(REAL_ID)).toBe(true);
  });

  it("rejects streaming and local placeholders", () => {
    expect(isPersistedMessageId("streaming-assistant")).toBe(false);
    expect(isPersistedMessageId("local-user-1710000000000")).toBe(false);
    expect(isPersistedMessageId("")).toBe(false);
    expect(isPersistedMessageId(undefined)).toBe(false);
  });
});

describe("canRateAssistantMessage", () => {
  it("allows thumbs only on a finished assistant turn with a real message id", () => {
    expect(
      canRateAssistantMessage({
        role: "assistant",
        id: REAL_ID,
        isStreaming: false,
      })
    ).toBe(true);
  });

  it("hides thumbs while streaming or on user / hidden / placeholder bubbles", () => {
    expect(
      canRateAssistantMessage({
        role: "assistant",
        id: REAL_ID,
        isStreaming: true,
      })
    ).toBe(false);
    expect(
      canRateAssistantMessage({
        role: "assistant",
        id: "streaming-assistant",
        isStreaming: false,
      })
    ).toBe(false);
    expect(canRateAssistantMessage({ role: "user", id: REAL_ID })).toBe(false);
    expect(
      canRateAssistantMessage({
        role: "assistant",
        id: REAL_ID,
        hidden: true,
      })
    ).toBe(false);
  });
});

describe("isCsatValue", () => {
  it("accepts integers 1–5 only", () => {
    expect(isCsatValue(1)).toBe(true);
    expect(isCsatValue(5)).toBe(true);
    expect(isCsatValue(0)).toBe(false);
    expect(isCsatValue(6)).toBe(false);
    expect(isCsatValue(3.5)).toBe(false);
  });
});

describe("buildThumbsEvent", () => {
  it("builds the locked thumbs payload and omits lesson_id on onboarding", () => {
    expect(
      buildThumbsEvent({
        surface: "onboarding",
        sessionId: "sess-1",
        messageId: REAL_ID,
        thumb: -1,
      })
    ).toEqual({
      kind: "thumbs",
      surface: "onboarding",
      session_id: "sess-1",
      message_id: REAL_ID,
      value: { thumb: -1 },
    });
  });

  it("includes lesson_id for lesson surface", () => {
    const event = buildThumbsEvent({
      surface: "lesson",
      sessionId: "sess-2",
      messageId: REAL_ID,
      lessonId: "lesson-9",
      thumb: 1,
    });
    expect(event.lesson_id).toBe("lesson-9");
    expect(event.surface).toBe("lesson");
  });
});

describe("submitQualityEvent", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("POSTs JSON to /api/v1/quality/events and accepts 204", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);

    await submitQualityEvent("tok", {
      kind: "thumbs",
      surface: "lesson",
      session_id: "sess-2",
      message_id: REAL_ID,
      lesson_id: "lesson-9",
      value: { thumb: 1 },
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/api/v1/quality/events");
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual({
      kind: "thumbs",
      surface: "lesson",
      session_id: "sess-2",
      message_id: REAL_ID,
      lesson_id: "lesson-9",
      value: { thumb: 1 },
    });
    const headers = new Headers(init.headers);
    expect(headers.get("Authorization")).toBe("Bearer tok");
  });

  it("throws on a non-success status so the caller can swallow quietly", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("nope", { status: 404 })));

    await expect(
      submitQualityEvent("tok", {
        kind: "thumbs",
        surface: "onboarding",
        session_id: "sess-1",
        message_id: REAL_ID,
        value: { thumb: 1 },
      })
    ).rejects.toThrow(/404/);
  });
});
