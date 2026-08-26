import { describe, expect, it } from "vitest";

import { hasQuestionMark, isPlanStreamContent } from "./chat";

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
