import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  applyChatSseEvent,
  ChatStreamError,
  consumeChatSse,
  emptyChatSseState,
  metadataFromStructured,
  readSseFrames,
} from "./chat-stream.ts";

function frame(event: string, data: unknown): string {
  return `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
}

describe("readSseFrames", () => {
  it("parses a full turn and leaves a partial frame buffered", () => {
    const raw = frame("token", { delta: "Hi" }) + "event: done\ndata: {";
    const { frames, rest } = readSseFrames(raw);
    assert.equal(frames.length, 1);
    assert.equal(frames[0].event, "token");
    assert.deepEqual(frames[0].data, { delta: "Hi" });
    assert.match(rest, /done/);
  });
});

describe("applyChatSseEvent", () => {
  it("appends many token deltas", () => {
    let state = emptyChatSseState();
    state = applyChatSseEvent(state, "token", { delta: "Hel" });
    state = applyChatSseEvent(state, "token", { delta: "lo" });
    assert.equal(state.content, "Hello");
    assert.equal(state.messageId, null);
  });

  it("accepts one fallback delta that is the whole reply", () => {
    let state = emptyChatSseState();
    state = applyChatSseEvent(state, "token", { delta: "Here is the next question." });
    state = applyChatSseEvent(state, "structured", {
      content: "Here is the next question.",
      course_roadmap: null,
    });
    state = applyChatSseEvent(state, "done", { message_id: "m1" });
    assert.equal(state.content, "Here is the next question.");
    assert.equal(state.messageId, "m1");
    assert.equal(state.metadata.course_roadmap_draft, undefined);
  });

  it("maps the onboarding roadmap and lesson fields from the structured reply", () => {
    const roadmap = {
      version: 1,
      summary: { goal_outcome: "Travel", goal_horizon: "3 months", starting_level: "A1", target_plan_days: 30 },
      milestones: [{ index: 1, title: "Greetings" }],
    };
    const onboarding = metadataFromStructured({ content: "Your plan.", course_roadmap: roadmap });
    assert.equal(onboarding.metadata.course_roadmap_draft?.summary.goal_outcome, "Travel");

    let state = emptyChatSseState();
    state = applyChatSseEvent(state, "token", { delta: "One moment." });
    state = applyChatSseEvent(state, "tool_start", { name: "language_policy" });
    state = applyChatSseEvent(state, "tool_end", { name: "language_policy" });
    state = applyChatSseEvent(state, "structured", {
      content: "Now the target language.",
      corrections: [{ span: "yo soy", correction: "soy", type: "grammar", note: "Drop the pronoun." }],
      tips: ["Short sentences."],
      suggest_finish: true,
      practiced: [{ aspect: "grammar", item: "ser", result: "shaky" }],
      timing: { active_minutes: 14, target_minutes: 15 },
    });
    assert.equal(state.content, "Now the target language.");
    assert.equal(state.metadata.corrections?.[0].correction, "soy");
    assert.deepEqual(state.metadata.tips, ["Short sentences."]);
    assert.equal(state.metadata.suggest_finish, true);
    assert.equal(state.metadata.practiced?.[0].result, "shaky");
    assert.deepEqual(state.metadata.timing, { active_minutes: 14, target_minutes: 15 });
  });

  it("rejects a done event that has no message id", () => {
    assert.throws(
      () => applyChatSseEvent(emptyChatSseState(), "done", {}),
      (error: unknown) => error instanceof ChatStreamError && error.code === "STREAM_INTERRUPTED"
    );
  });

  it("throws the SSE error and does not treat it as done", () => {
    assert.throws(
      () => applyChatSseEvent(emptyChatSseState(), "error", { code: "LLM_TIMEOUT", detail: "The coach timed out." }),
      (error: unknown) => {
        assert.ok(error instanceof ChatStreamError);
        assert.equal(error.code, "LLM_TIMEOUT");
        assert.equal(error.message, "The coach timed out.");
        return true;
      }
    );
  });
});

describe("consumeChatSse", () => {
  it("plays one chunk of many deltas, then structured metadata, then done", async () => {
    const raw =
      frame("token", { delta: "Hel" }) +
      frame("token", { delta: "lo" }) +
      frame("structured", { content: "Hello", tips: ["Wave."] }) +
      frame("done", { message_id: "abc" });
    const seen: string[] = [];
    const state = await consumeChatSse(streamOf(raw), (update) => {
      seen.push(update.content);
    });
    assert.deepEqual(seen, ["Hel", "Hello", "Hello"]);
    assert.equal(state.messageId, "abc");
    assert.deepEqual(state.metadata.tips, ["Wave."]);
  });

  it("stops on an error event without a message id", async () => {
    const raw = frame("token", { delta: "Hi" }) + frame("error", { code: "PERSIST_FAILED", detail: "Could not save this turn. Please try again." });
    await assert.rejects(
      () => consumeChatSse(streamOf(raw), () => {}),
      (error: unknown) => error instanceof ChatStreamError && error.code === "PERSIST_FAILED"
    );
  });
});

function streamOf(text: string): ReadableStream<Uint8Array> {
  return new ReadableStream({
    start(controller) {
      controller.enqueue(new TextEncoder().encode(text));
      controller.close();
    },
  });
}
