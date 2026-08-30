# Miner inbox

Stubs from `python -m evals.mine`. **Not a ship gate.** `--suite regression`
and `--suite all` do not load this folder.

Generated `*.yaml` files are gitignored. Promote by hand after stripping PII.

## Promote a stub

1. Open a stub. Confirm the failure is real (not a one-off thumbs-down).
2. Strip remaining PII. Replace `user_message` and notes with anonymized text.
   Never copy a production transcript into git.
3. Move the file to `evals/cases/regression/` (or `capability/` if it is gold).
4. Set `suite: regression`, fill `checks.deterministic` from `suggested_checks`,
   drop `suggested_checks`.
5. Point `input.context_fixture` at an anonymized JSON under `evals/fixtures/`.
6. Add `evals/fixtures/replay/<id>.json` (live run or a hand-written completion).
7. Re-run:

   ```bash
   PYTHONPATH=apps/backend:. python -m evals.run --suite regression --replay
   ```
