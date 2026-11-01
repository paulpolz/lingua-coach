"""Run one eval dataset against the real LLM and record an experiment in LangSmith.

    uv run python -m evals.run --dataset lesson_turns [--prefix <git-sha>] [--min-score 0.9]

Needs LANGSMITH_API_KEY and the LLM API key. The dataset is created in LangSmith from
`evals/datasets/<name>.jsonl` on first use; later examples are added in the UI (for example
"Add to dataset" from a staging trace). Exits 1 when any evaluator's mean score is below
`--min-score`, so the nightly workflow fails on a regression.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from langsmith import Client
from langsmith.evaluation import aevaluate

from evals.evaluators import EVALUATORS
from evals.targets import TARGETS

DATASETS_DIR = Path(__file__).parent / "datasets"


def load_examples(name: str) -> list[dict[str, Any]]:
    lines = (DATASETS_DIR / f"{name}.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def ensure_dataset(client: Client, name: str) -> None:
    if client.has_dataset(dataset_name=name):
        return
    dataset = client.create_dataset(name, description=f"Lingua Coach eval set: {name}")
    client.create_examples(dataset_id=dataset.id, examples=load_examples(name))


def _git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return "local"


async def run(name: str, prefix: str, min_score: float) -> int:
    client = Client()
    ensure_dataset(client, name)
    results = await aevaluate(
        TARGETS[name],
        data=name,
        evaluators=EVALUATORS[name],  # type: ignore[arg-type]
        experiment_prefix=f"{name}-{prefix}",
        max_concurrency=2,
        client=client,
    )
    scores: dict[str, list[float]] = defaultdict(list)
    async for row in results:
        for result in row["evaluation_results"]["results"]:
            if result.score is not None:
                scores[result.key].append(float(result.score))
    failed = False
    for key, values in sorted(scores.items()):
        mean = sum(values) / len(values)
        failed |= mean < min_score
        print(f"{key}: {mean:.2f} over {len(values)} examples")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", required=True, choices=sorted(TARGETS))
    parser.add_argument("--prefix", default=os.environ.get("GITHUB_SHA", "")[:7] or _git_sha())
    parser.add_argument("--min-score", type=float, default=0.9)
    args = parser.parse_args(argv)
    return asyncio.run(run(args.dataset, args.prefix, args.min_score))


if __name__ == "__main__":
    sys.exit(main())
