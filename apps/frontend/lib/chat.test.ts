import { describe, expect, it } from "vitest";

import { applyChecklistMetadata, CHAT_EXTERNAL_LINK, hasQuestionMark, isPlanStreamContent } from "./chat";

describe("isPlanStreamContent", () => {
  it("matches json:course_roadmap without English headings", () => {
    const spanishPlan = [
      "Aquí tienes tu plan personalizado.",
      "",
      "```json:course_roadmap",
      '{"version":1,"summary":{"target_language":"es"}}',
      "```",
    ].join("\n");
    expect(isPlanStreamContent(spanishPlan)).toBe(true);
  });

  it("still matches legacy English heading extras", () => {
    expect(isPlanStreamContent("# Your course roadmap\n\n## Milestones")).toBe(true);
  });

  it("does not treat ordinary chat as a plan", () => {
    expect(isPlanStreamContent("¿Cuál es tu idioma nativo?")).toBe(false);
  });
});

describe("hasQuestionMark", () => {
  it("treats fullwidth ？ like ASCII ?", () => {
    expect(hasQuestionMark("Ready to start?")).toBe(true);
    expect(hasQuestionMark("準備はいい？")).toBe(true);
    expect(hasQuestionMark("Aquí tienes tu plan.")).toBe(false);
  });
});

describe("applyChecklistMetadata", () => {
  const tasks = [
    { id: "warmup", label: "Warm-up", minutes: 5 },
    { id: "grammar", label: "Grammar", minutes: 8 },
  ];

  it("adds completed_task_ids from task_update", () => {
    const next = applyChecklistMetadata(
      { task_update: { completed_task_ids: ["warmup"] } },
      tasks,
      new Set()
    );
    expect([...next.completedIds]).toEqual(["warmup"]);
    expect(next.tasks).toEqual(tasks);
  });

  it("marks every task complete when suggest_finish is true", () => {
    const next = applyChecklistMetadata({ suggest_finish: true }, tasks, new Set(["warmup"]));
    expect(next.completedIds).toEqual(new Set(["warmup", "grammar"]));
  });

  it("replaces the task list from lesson_plan and drops stale ids", () => {
    const next = applyChecklistMetadata(
      { lesson_plan: { tasks: [{ id: "production", label: "Role play", minutes: 10 }] } },
      tasks,
      new Set(["warmup"])
    );
    expect(next.tasks).toEqual([{ id: "production", label: "Role play", minutes: 10 }]);
    expect(next.completedIds.size).toBe(0);
  });
});

describe("CHAT_EXTERNAL_LINK", () => {
  it("opens catalog and other assistant links in a new tab", () => {
    expect(CHAT_EXTERNAL_LINK.target).toBe("_blank");
    expect(CHAT_EXTERNAL_LINK.rel).toBe("noopener noreferrer");
  });
});
