# Learner memory in each LLM call

Each coach call sends a small selection of what we already know about the learner. The selection is plain SQL and Python in [`memory.py`](../../apps/backend/app/services/memory.py) and [`prompt_assembly.py`](../../apps/backend/app/services/prompt_assembly.py). There is no retriever, no embedding model, and no pgvector table. That search was designed and not built: the caps below already stop the prompt from growing with every lesson, and the evals have not shown that the picker drops something the coach needed.

## What each call receives

| Call | Selection |
|------|-----------|
| Lesson chat | Top 10 open mistakes, ranked for this lesson |
| Lesson generation | Top 15 open mistakes, plus the last 2 finished lessons in full and the 3 before those as one line each |
| Report update | Snapshot sections in full. `update_log` and `daily_log` send the last 5 entries, at most 3,000 characters |

Closed mistakes (`resolved_at` set) are not candidates.

Mistake score, in [`rank_mistakes`](../../apps/backend/app/services/memory.py):

```
score = 3 × (pattern shares a word of 4+ letters with the focus)
      + 2 × (review is due)
      + 0.5 × min(occurrence_count, 5)
```

Lesson chat takes its focus words from this lesson's grammar focus and vocab theme. Lesson generation takes them from the current roadmap milestone and block.

## Report logs

`update_log` and `daily_log` only grow. The model writes the new line; [`report_ops`](../../apps/backend/app/services/report_ops.py) appends it to the full body. The prompt shows the tail and marks it `(showing the last 5 of N entries)`. A `patch_section` on a log section is rejected, so a trimmed view cannot replace the history. Snapshot sections (`latest_session`, `progress_table`, `pattern_tracker`, `confusion_list`, and the roadmap reports) are sent whole.

Prompt builders log `context_tokens` per block (`estimate_input_tokens`, 4 characters per token) so growth is visible before it shows up in cost.
