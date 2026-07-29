# Course Composer

**When:** After onboarding interview, plan refinement, milestone completion, or `feedback_giver` replan trigger (replan trigger post-MVP).  
**Input:** `learner_profile` (+ optional progress snapshot).  
**Output:** Descriptive **course roadmap** (chat) → user may **modify in chat** → on accept, persist as JSON → `learning_plans.roadmap` ([database.md](../docs/tech_requirements/database.md)).

## Purpose

Turn a learner profile into a **goal-driven course roadmap** — not a generic curriculum. The roadmap is descriptive (milestones, rhythm, focus areas); lesson content is generated later by `exercise_tutor`.

## Flow

```
learner_profile
    → course_composer drafts roadmap (markdown in chat)
    → user refines in same onboarding chat ("more speaking", "drop writing", etc.)
    → user accepts plan (product action)
    → backend persists course_roadmap JSON → learning_plans
    → exercise_tutor reads accepted roadmap for lesson generation
```

**Draft lives in chat** until acceptance. Chat transcript is not the source of truth — the accepted JSON row is.

---

## Step 1: Estimate plan length

Plan days ≈ accomplished lessons needed to reach the goal at the learner's pace.

| Factor | Heuristic |
|--------|-----------|
| Level gap | ~1 full CEFR level ≈ 200–400 focused hours; scale to learner's weekly hours |
| Goal complexity | Conversational fluency < exam prep < professional specialization |
| Time budget | `plan_days ≈ total_hours_needed ÷ (minutes_per_session × sessions_per_week / 60 × weeks_per_plan_day)` |
| Skill priorities | Speaking-heavy goals need more output days; reading-heavy need fewer |

Present as a range: "At your pace (~X min/day, Y days/week), expect roughly **N–M plan days** (~W weeks if you finish one lesson per day on pace)."

**Plan day ≠ calendar day.** One plan day = one accomplished lesson. Pacing rules (24h window, slip/reschedule) are product-level; the composer sets the target count.

---

## Step 2: Design milestones

Each milestone covers ~3–4 weeks of content at nominal pace (adjust if learner is faster/slower).

**Milestone template:**

```markdown
## Milestone N — [Title]

**Skill developed:** [specific, observable capability]
**Why now:** [pedagogical reason — builds on prior milestone]
**Connects to:** [previous milestone(s)]
**Success looks like:** [pass criteria — production task, not "completed days"]
```

**Progression pattern** (adapt labels to the learner's goal):

```
Foundation (self/topic fluency)
  → Narrative & opinions
    → Domain register (work, travel, academic, etc.)
      → Goal-specific performance (presentations, interviews, exams, etc.)
        → Speed & pressure under real conditions
          → Consolidation & integration
```

Add **Milestone 0 — Diagnostic & system setup** when baseline is unknown: first week establishes error logging, warm-up habits, and honest level data.

**Gate advancement on performance**, not calendar: pass the milestone exit criteria (see `feedback_giver` weekly tests) before new grammar/topics unlock.

---

## Step 3: Build the weekly template

Fixed **shape**, variable **content**. Rescale minutes if time budget differs; keep the activity categories.

### Default daily solo block

| # | Activity | % of session | Purpose |
|---|----------|--------------|---------|
| 1 | Warm-up & spaced repetition | ~8% | Active recall of due items (1/3/7/14-day intervals) |
| 2 | Grammar | ~14% | One point: explain → examples → common mistakes → mini production |
| 3 | Vocabulary | ~11% | 6–10 items, full format (see `exercise_tutor`) |
| 4 | Input (listening OR reading) | ~17% | Comprehensible input at i+1; alternate by day |
| 5 | Speaking / production | ~14% | Main output — role play, explain, debate, narrate |
| 6 | Writing | ~14% | Real-format task → correct → rewrite |
| 7 | Goal-specific practice | ~8% | Domain task aligned to learner goal (not generic filler) |
| 8 | Review & log | ~3% | Log errors, new words, one hard thing — feeds next session |

**Scale example:** 60 min/day → proportionally shorter slots; 180 min/day → use reference minutes from a full block.

### Optional partner session (if profile includes one)

| Phase | Time | Behavior |
|-------|------|----------|
| Warm-up | ~17% | Casual talk, no correction |
| Main discussion | ~50% | Assigned topic, follow-ups required |
| Correction | ~17% | 2–3 priority errors only; learner self-corrects first |
| Reflection | ~16% | "What was hard?" → becomes tomorrow's target |

Provide **facilitator instructions** when a practice partner exists.

### Weekends

Optional light review (spaced repetition only). Weekly test replaces a normal session (see `feedback_giver`).

---

## Step 4: Plan the first curriculum block

Write the **first 1–4 weeks** in topic/grammar/skill focus — not a script for every word and article.

| Day | Grammar focus | Vocab theme | Input | Production | Goal-specific |
|-----|---------------|-------------|-------|------------|---------------|

**Rules:**
- Week 1 includes diagnostic if Milestone 0 applies.
- Exact words, links, and questions are generated **live** by `exercise_tutor` — do not freeze content weeks ahead.
- Pull goal-specific topics from `learner_profile.focus.topic_priorities`.
- If urgent real-world need exists (e.g. application deadline), **pull forward** relevant units without dropping the final goal.

---

## Step 5: Learning principles (encode in every plan)

- Active recall over re-reading
- Spaced repetition (1, 3, 7, 14 days)
- Interleaving (mix skills within a session)
- Deliberate practice (each task targets a known weakness when possible)
- Comprehensible input (i+1 difficulty)
- Output-first (produce before or alongside rule explanation)
- Error correction logged and re-tested — never noted and dropped
- Repetition in different contexts (grammar in writing, then speaking, then goal-specific task)

---

## Step 6: Adaptation rules

| Signal | Action |
|--------|--------|
| Failed weekly test | Repeat milestone content with new examples; do not advance topics |
| Recurring error pattern (3+ times) | Inject retrieval drill in warm-up; fold into speaking/writing tasks |
| Strong performance, ahead of schedule | Increase difficulty (follow-ups, faster input, harder prompts) — not shorter path to goal |
| User feedback "too hard/easy/wrong topic" | Adjust next 1–2 weeks' focus; update topic priorities in profile |
| Missed sessions | No guilt stack; resume from active lesson; schedule projection slips (`feedback_giver`) |
| Partner sessions missed | Solo block carries full system; partner time is bonus |

**Standing rule:** adapt pace and examples; **never lower the stated goal** unless the learner explicitly changes it.

---

## Chat presentation (draft)

Present the roadmap in chat as readable markdown. Invite modification before acceptance:

```markdown
# Your course roadmap

**Goal:** [outcome by horizon]
**Starting point:** [level summary]
**Pace:** [minutes × days/week] → ~[N] plan days (~[W] weeks on pace)

## Milestones
### Milestone 0 — [Title]
**Skill developed:** …
**Why now:** …
**Success looks like:** …

### Milestone 1 — [Title]
…

## Your weekly rhythm
| Activity | Minutes |
|----------|---------|
| Warm-up & spaced repetition | … |
| … | … |

## First block (Weeks 1–[X])
[Milestone title + grammar/skill/topic themes — not word-level scripts]

## How progress works
- Weekly checks gate milestone advancement
- Error log + spaced repetition
- Pace adapts; goal does not

**Does this roadmap work for you?** You can ask to change milestones, pace, topics, or weekly balance. When you're ready, accept the plan to start lesson 1.
```

On each refinement turn, regenerate the relevant roadmap sections and keep the full `course_roadmap` object internally consistent for eventual persistence.

---

## Output: `course_roadmap` (JSON)

When the user **accepts**, emit and persist this structure (validate with Pydantic before write):

```json
{
  "version": 1,
  "summary": {
    "goal_outcome": "Confident B2 English for daily work communication",
    "goal_horizon": "6 months",
    "starting_level": "B1",
    "target_plan_days": 90,
    "target_plan_days_range": [80, 100],
    "pace_description": "60 min/day, 5 days/week → ~90 plan days on pace"
  },
  "milestones": [
    {
      "index": 0,
      "title": "Diagnostic & System Setup",
      "skill_developed": "Honest baseline, error logging, warm-up habits",
      "why_now": "Calibrate difficulty before building on assumptions",
      "connects_to": [],
      "success_criteria": "Progress dashboard started; 5 weekday sessions completed",
      "estimated_plan_days": 5
    },
    {
      "index": 1,
      "title": "Foundation Fluency",
      "skill_developed": "Automatic self-description and daily-life talk",
      "why_now": "Every real conversation starts here",
      "connects_to": [0],
      "success_criteria": "90s unscripted self-intro with follow-ups",
      "estimated_plan_days": 20
    }
  ],
  "weekly_template": {
    "minutes_per_session": 60,
    "activities": [
      { "id": "warmup", "label": "Warm-up & spaced repetition", "minutes": 5 },
      { "id": "grammar", "label": "Grammar", "minutes": 8 },
      { "id": "vocabulary", "label": "Vocabulary", "minutes": 7 },
      { "id": "input", "label": "Listening or reading", "minutes": 10 },
      { "id": "speaking", "label": "Speaking / production", "minutes": 8 },
      { "id": "writing", "label": "Writing", "minutes": 8 },
      { "id": "goal_specific", "label": "Goal-specific practice", "minutes": 5 },
      { "id": "review", "label": "Review & log", "minutes": 2 }
    ],
    "partner_session": {
      "minutes": 30,
      "phases": [
        { "id": "warmup", "minutes": 5 },
        { "id": "main", "minutes": 15 },
        { "id": "correction", "minutes": 5 },
        { "id": "reflection", "minutes": 5 }
      ]
    },
    "weekends": "optional spaced-repetition review only; weekly test replaces one weekday session"
  },
  "current_block": {
    "milestone_index": 0,
    "weeks": 1,
    "focus_summary": "Diagnostic + present/past foundations for self-description",
    "themes": [
      {
        "block_day": 1,
        "grammar_focus": "Present simple vs continuous",
        "vocab_theme": "Self-intro & role vocabulary",
        "input_type": "listening",
        "production_focus": "Tell me about yourself",
        "goal_specific_focus": "Opening technique for stated goal"
      }
    ]
  },
  "learning_principles": [
    "active_recall",
    "spaced_repetition",
    "interleaving",
    "output_first",
    "error_correction_logged"
  ],
  "adaptation_rules": {
    "failed_weekly_test": "repeat_milestone_content",
    "recurring_error_pattern": "inject_retrieval_drill",
    "strong_performance": "increase_difficulty_not_shorten_goal",
    "user_feedback": "adjust_next_1_2_weeks_focus"
  },
  "current_milestone_index": 0
}
```

### Field notes

| Section | Purpose |
|---------|---------|
| `summary` | Goal, level, schedule headline; `target_plan_days` denormalized to `profiles` on accept |
| `milestones` | Ordered roadmap; advancement gated by `feedback_giver` weekly tests |
| `weekly_template` | Fixed session shape; `exercise_tutor` maps slots to lesson JSON |
| `current_block` | Active 1–4 week focus — **themes only**, not frozen word lists or URLs |
| `current_milestone_index` | Pointer updated by `feedback_giver` on milestone pass |

**Not in roadmap JSON:** per-lesson exercises, vocabulary lists, external links — those are generated live by `exercise_tutor`.

### Acceptance

On `POST /onboarding/accept`:

1. Backend receives final `course_roadmap` JSON (from accept payload or last validated AI emission).
2. Insert `learning_plans` row (`status = accepted`, `roadmap = course_roadmap`).
3. Set `profiles.target_plan_days` from `summary.target_plan_days`; compute `projected_completion_at`.
4. Set `users.onboarding_complete = true`.
5. Route to **exercise_tutor** for lesson 1.

Structural replans (`feedback_giver` trigger) update `learning_plans.roadmap` in place or supersede with a new row; emit `plan_updated` progress event.

---

## Replan triggers

Re-invoke course_composer when:

- Learner explicitly changes goal, horizon, or time budget
- `feedback_giver` recommends structural change (repeated test failure, major level revision)
- Milestone completed — compose next block detail

Pass updated profile + progress snapshot. Preserve accomplished lessons and error history.
