# Feedback Giver

> **Post-MVP — out of scope for first release.** MVP relies on `exercise_tutor` session summaries, `mistakes`, pace fields on `profiles`, and dashboard pace hints. Do not implement progress dashboard rows, weekly assessment gates, or automated replan triggers until this skill ships.

**When:** After lesson completion, at week boundaries, on progress requests, or when replanning is needed.  
**Input:** Session summaries, error log, learner profile, active plan, lesson history.  
**Output:** Progress dashboard, recommendations, plan adjustments, learner-facing feedback.

## Purpose

Close the loop: turn session outputs into **structured progress**, **actionable feedback**, and **plan updates**. The learner should always know whether they're on track and what to focus on next.

---

## Progress dashboard

Maintain one row per skill category. **Adapt categories** to the learner's goal — defaults below; rename or drop irrelevant ones.

| Category | Current | Target | Progress % | Weaknesses | Recommendations |
|----------|---------|--------|------------|------------|-----------------|

**Default categories:** Grammar, Vocabulary, Listening, Speaking, Reading, Writing, Goal-specific readiness (e.g. "Presentation readiness", "Travel confidence", "Interview readiness"), Confidence.

### Scoring guidance

- **Progress %** — heuristic from lessons completed within milestone + test performance + error trend (not linear time).
- **Weaknesses** — top 1–3 **patterns**, not single typos. Group errors into named patterns (e.g. "missing articles", "speed vs accuracy on to-be").
- **Recommendations** — one concrete action each (next drill, resource type, behavior change).

### Update after every accomplished lesson

Append to **update log** (date, 2–4 sentences: what happened, what's carried forward).

### Open items

Track deferred tasks, unfinished follow-ups, and queued drills explicitly — `exercise_tutor` picks these up first.

---

## Error log analysis

### Pattern taxonomy

Group errors into **recurring patterns** with IDs. Examples (language-learning):

| Pattern type | Example |
|--------------|---------|
| Missing function words | dropped "to be", missing "to" before infinitive |
| Morphology | 3rd person -s, irregular past |
| Articles | missing a/the, overcorrection |
| Prepositions / fixed phrases | wrong preposition, verb+prep |
| Word form / class | noun vs adjective, false friends |
| Word order | adverb placement, embedded questions |
| Register / collocation | informal in formal context |

For **non-language goals**, define domain-specific patterns (e.g. "weak thesis statement", "missing quantified result in case story").

### Spaced repetition schedule

Each pattern re-tested at **+1, +3, +7, +14 days** from first log or last failure.

When a pattern appears **3+ times in live production** (not just drills), flag as **priority** → `exercise_tutor` injects warm-up retrieval and elicits the pattern in speaking/writing.

When clean on structured drill **but fails in free speech**, tag as **speed/attention issue** — recommend contrast drill (careful vs fast round).

---

## Pacing and schedule

| Term | Rule |
|------|------|
| Plan day | One accomplished lesson |
| On pace | Finished within 24h of lesson `started_at` |
| Behind | Finish after 24h → projection slips one plan day; **do not block** next lesson |
| Projection | `plan_days_remaining` from active_plan schedule minus accomplished count, adjusted for slip |

Surface minimal hints: plan days done / target, on pace or behind, projected completion date.

---

## Weekly assessment (milestone gate)

Run at end of each week (or every N plan days). Replaces a normal session.

| Test | Duration | Pass criterion |
|------|----------|----------------|
| Grammar | ~10 min | **Produce** week's points in new sentences — not recognition |
| Vocabulary | ~10 min | Active recall in context |
| Input | ~10 min | New clip/text at week's level + comprehension |
| Speaking | ~10 min | Cold, unrehearsed prompt — recorded if possible |
| Goal-specific | ~10–15 min | Simulation aligned to learner goal |
| Writing | ~10 min | Timed first draft, one real format |

**Pass week →** advance topics in next block. **Fail →** repeat milestone content with new examples; invoke `course_composer` to extend current block — goal unchanged.

Share results in plain language: what improved, what blocked advancement, exact next focus.

---

## Learner-facing feedback template

```markdown
## Progress update — [date]

**This session:** [1–2 sentences on what you did and how it went]

**What's working:** [specific strengths — cite examples from their production]

**Priority focus:** [1–3 patterns or skills with clear next step]

**Open items:** [deferred tasks, follow-ups]

**Pace:** [on pace / behind by X plan days — only if relevant]

**Next session:** [concrete preview — grammar, topic, task type]
```

Tone: direct, specific, encouraging. No vague "keep practicing."

---

## Plan modification rules

### Automatic (`exercise_tutor` applies next session)

- Inject retrieval for priority error patterns
- Adjust difficulty (more follow-ups if strong; narrower task if struggling)
- Clear open items before new content
- Shift skill mix if user feedback repeats (e.g. third request for "more speaking" → +10 min speaking, trim input)

### Structural (invoke `course_composer`)

- Failed weekly test twice on same milestone
- Learner changes goal, horizon, or time budget
- Level assessment was wrong by > half a CEFR band after diagnostic week
- Goal-specific readiness stuck below 30% for 3+ weeks despite consistent practice

Propose changes in chat; user confirms before replacing active_plan.

```markdown
## Suggested plan adjustment

**Reason:** [evidence from tests/errors/feedback]
**Change:** [what moves — topics, milestone length, pace, priorities]
**Unchanged:** [goal and success criteria — unless user requested change]
**Accept / modify?**
```

---

## Confidence and motivation

Track **Confidence** as its own row when useful — engagement, frustration signals, avoidance patterns (not language errors).

If frustration detected: acknowledge, narrow session scope, preserve goal. Never shame missed days.

---

## Integration summary

```
exercise_tutor ──session summary──► feedback_giver
                                        │
                    ┌───────────────────┼───────────────────┐
                    ▼                   ▼                   ▼
             progress dashboard    recommendations    plan adjustment?
                    │                                       │
                    └──────────► exercise_tutor ◄───────────┘
                                        ▲
                              course_composer (if replan)
```

After each update, ensure `exercise_tutor`'s next generation reads the latest dashboard, error priorities, and open items.
