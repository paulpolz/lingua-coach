# CI

GitHub Actions (`.github/workflows/ci.yml`) runs three jobs in parallel on every pull request and every push to `main`:

| Job | What |
|-----|------|
| `backend-test` | Postgres 16 (`lingua`/`lingua` / `lingua_coach` on 5432) + `uv run pytest` in `apps/backend` |
| `evals-replay` | `python -m evals.run --suite regression --replay` with **no** `GEMINI_API_KEY` |
| `frontend-test` | `npm ci`, lint, typecheck, `vitest run` in `apps/frontend` |

## Replay command

`uv run --directory apps/backend` would leave the process cwd in `apps/backend`, so the repo-root `evals` package would not import. CI syncs the backend venv, then invokes that interpreter from the repo root:

```bash
cd apps/backend && uv sync --extra dev
cd "${GITHUB_WORKSPACE}"
export PYTHONPATH="${GITHUB_WORKSPACE}/apps/backend:${GITHUB_WORKSPACE}"
apps/backend/.venv/bin/python -m evals.run --suite regression --replay
```

`PYTHONPATH` is backend first (`app.*`) then repo root (`evals`). Run artifacts under `evals/results/` are gitignored and uploaded as a workflow artifact when present.

## Required status check

After the first green `evals-replay` run on `main`, enable **`evals-replay`** as a required status check on branch-protected `main` (GitHub settings; the workflow cannot be required until it has run once). The runner and regression cases are in the tree; this job should pass on replay fixtures with no API key.
