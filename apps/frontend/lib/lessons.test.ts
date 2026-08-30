import { describe, expect, it } from "vitest";

import { buildFinishLessonBody } from "./lessons";

describe("buildFinishLessonBody", () => {
  it("allows an empty finish (no CSAT, no comment)", () => {
    expect(buildFinishLessonBody({})).toEqual({});
    expect(buildFinishLessonBody({ learner_feedback: "   " })).toEqual({});
    expect(buildFinishLessonBody({ csat: 0 })).toEqual({});
  });

  it("keeps a valid 1–5 CSAT and trimmed feedback", () => {
    expect(
      buildFinishLessonBody({
        csat: 4,
        learner_feedback: "  too fast  ",
        completed_slot_ids: ["slot-a"],
      })
    ).toEqual({
      csat: 4,
      learner_feedback: "too fast",
      completed_slot_ids: ["slot-a"],
    });
  });
});
