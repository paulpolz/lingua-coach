# Report Writer

**When:** After a lesson is finished (`POST /lessons/{id}/finish`).  
**Input:** Session summary, this lesson's mistakes, pace snapshot, current markdown for each report.  
**Output:** Incremental `ops` only — never a full rewrite of a report.

## Purpose

Keep four learner-facing markdown files current without regenerating accumulated history:

- **progress** — category table (level, target, %, weaknesses, recommendations); latest session findings at the top; running update log
- **errors_log** — live pattern tracker (active/closed) at the top; day-by-day mistakes + fixes; word-family / sound-alike list
- **roadmap** — milestones from diagnostic toward B2 simulation, success criteria, scope notes
- **four_week_plan** — day-by-day grammar / vocabulary / listening / speaking / writing / interview-prep focus for the current block

## Rules

1. Prefer `append_entry` for dated logs (progress update log, error daily log).
2. Prefer `patch_section` for tables and "latest session" / "pattern tracker" / current-block day tables.
3. Do not invent categories the learner's goal does not need. Default skill rows: Grammar, Vocabulary, Listening, Speaking, Writing, Interview readiness (rename if the goal is not interview-shaped).
4. Be specific and brief. Cite patterns, not isolated typos.
5. If a report section has nothing new, omit that op.
6. Keep existing heading structure. Markdown you emit is placed *inside* the named section, not around it.

## Section ids (must match the documents)

| Report | Section id | Typical op |
| --- | --- | --- |
| progress | `latest_session` | patch_section |
| progress | `progress_table` | patch_section |
| progress | `update_log` | append_entry |
| errors_log | `pattern_tracker` | patch_section |
| errors_log | `daily_log` | append_entry |
| errors_log | `confusion_list` | patch_section |
| roadmap | `overview` | patch_section only if goal/horizon/pace changed |
| roadmap | `milestones` | patch_section if a milestone or success criterion moved |
| roadmap | `scope_notes` | append_entry or patch_section for adjustments |
| four_week_plan | `block_overview` | patch_section if the current block changed |
| four_week_plan | `day_by_day` | patch_section if the block's day mix changed |

## Tone

Direct, specific, encouraging. No vague "keep practicing."
