"""Batch production LLM-as-judge over stored quality snapshots.

Not on the SSE / chat path. Reuses `evals/judges/*`. Writes `quality_events`
rows with `kind=judge`. Never logs full prompts.

From the repo root:

    PYTHONPATH=apps/backend:. python -m evals.judge_online
    PYTHONPATH=apps/backend:. python -m evals.judge_online --limit 25

Needs `GEMINI_API_KEY` and `DATABASE_URL` (same as the backend). If the API
key is missing, exits 0 with a message so cron/CI can call this safely.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any
from uuid import UUID

EVALS_ROOT = Path(__file__).resolve().parent
REPO_ROOT = EVALS_ROOT.parent

if str(REPO_ROOT / "apps" / "backend") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "apps" / "backend"))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.config import settings  # noqa: E402
from app.core.metrics import record_quality_judge_fail  # noqa: E402
from app.db.session import AsyncSessionLocal  # noqa: E402
from app.models.quality_event import QualityEvent  # noqa: E402
from app.services.quality import (  # noqa: E402
    KIND_JUDGE,
    KIND_JUDGE_CANDIDATE,
    KIND_THUMBS,
)
from evals.judges.runner import judge_once, resolve_rubric  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

_SURFACE_RUBRIC = {
    "lesson": "lesson_turn_v1",
    "onboarding": "onboarding_v1",
    "lesson_generation": "lesson_generation_v1",
}

_SKIP_NO_KEY = "GEMINI_API_KEY is not set; skipping online judge (exit 0)."


def _rubric_for_surface(surface: str) -> str:
    return _SURFACE_RUBRIC.get(surface, "lesson_turn_v1")


def _snapshot_from_value(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    snapshot = value.get("snapshot")
    if isinstance(snapshot, dict) and str(snapshot.get("assistant_text") or "").strip():
        return snapshot
    return None


def _case_and_fixture(surface: str, snapshot: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    snippet = snapshot.get("lesson_snippet") if isinstance(snapshot.get("lesson_snippet"), dict) else {}
    case = {
        "mode": surface,
        "locale": {"native": snapshot.get("native"), "target": snapshot.get("target")},
        "input": {"user_message": snapshot.get("user_message")},
    }
    fixture = {
        "goal_outcome": snapshot.get("goal"),
        "target_level": snapshot.get("level"),
        "learner_profile": {
            "native_language": snapshot.get("native"),
            "target_language": snapshot.get("target"),
        },
        "curriculum": snippet,
    }
    return case, fixture


async def _judged_message_ids(db: AsyncSession) -> set[UUID]:
    result = await db.execute(
        select(QualityEvent.message_id).where(
            QualityEvent.kind == KIND_JUDGE,
            QualityEvent.message_id.is_not(None),
        )
    )
    return {mid for mid in result.scalars().all() if mid is not None}


async def collect_unjudged(db: AsyncSession, *, limit: int) -> list[QualityEvent]:
    """Candidates first, then thumbs-down rows that still have a snapshot."""
    judged = await _judged_message_ids(db)
    result = await db.execute(
        select(QualityEvent)
        .where(QualityEvent.kind == KIND_JUDGE_CANDIDATE)
        .order_by(QualityEvent.created_at.asc())
    )
    picked: list[QualityEvent] = []
    candidate_message_ids: set[UUID] = set()
    for event in result.scalars().all():
        if event.message_id is not None and event.message_id in judged:
            continue
        if _snapshot_from_value(event.value) is None:
            continue
        picked.append(event)
        if event.message_id is not None:
            candidate_message_ids.add(event.message_id)
        if len(picked) >= limit:
            return picked

    remaining = limit - len(picked)
    if remaining <= 0:
        return picked

    thumbs = await db.execute(
        select(QualityEvent)
        .where(QualityEvent.kind == KIND_THUMBS)
        .order_by(QualityEvent.created_at.asc())
    )
    for event in thumbs.scalars().all():
        if remaining <= 0:
            break
        value = event.value if isinstance(event.value, dict) else {}
        if value.get("thumb") != -1:
            continue
        if event.message_id is not None and (
            event.message_id in judged or event.message_id in candidate_message_ids
        ):
            continue
        if _snapshot_from_value(value) is None:
            continue
        picked.append(event)
        remaining -= 1
    return picked


async def _judge_one(event: QualityEvent) -> dict[str, Any] | None:
    snapshot = _snapshot_from_value(event.value)
    if snapshot is None:
        return None
    from app.services.gemini import ChatTurn, generate_json

    rubric_name = _rubric_for_surface(event.surface)
    spec = resolve_rubric(rubric_name)
    case, fixture = _case_and_fixture(event.surface, snapshot)
    completion = str(snapshot.get("assistant_text") or "")
    result = await judge_once(
        spec,
        case=case,
        fixture=fixture,
        completion=completion,
        generate_json=generate_json,
        ChatTurn=ChatTurn,
    )
    record = result.as_record()
    record["candidate_id"] = str(event.id)
    record["model"] = settings.gemini_model_lesson
    record["rubric"] = spec.version
    return record


def _record_judge_fails(record: dict[str, Any]) -> None:
    scores = record.get("scores")
    rubric = str(record.get("rubric") or record.get("rubric_version") or "unknown")
    if not isinstance(scores, dict):
        return
    for dimension, score in scores.items():
        if score == "fail":
            record_quality_judge_fail(dimension=str(dimension), rubric=rubric)


async def run_batch(*, limit: int) -> dict[str, int]:
    stats = {"considered": 0, "written": 0, "skipped": 0, "errors": 0}
    async with AsyncSessionLocal() as db:
        items = await collect_unjudged(db, limit=limit)
        stats["considered"] = len(items)
        for event in items:
            try:
                record = await _judge_one(event)
            except Exception:  # noqa: BLE001 — one failure must not abort the batch
                stats["errors"] += 1
                continue
            if record is None:
                stats["skipped"] += 1
                continue
            if record.get("error") and not record.get("scores"):
                stats["errors"] += 1
            db.add(
                QualityEvent(
                    user_id=event.user_id,
                    kind=KIND_JUDGE,
                    surface=event.surface,
                    session_id=event.session_id,
                    message_id=event.message_id,
                    lesson_id=event.lesson_id,
                    value=record,
                )
            )
            _record_judge_fails(record)
            stats["written"] += 1
        await db.commit()
    return stats


def has_gemini_key() -> bool:
    return bool((settings.gemini_api_key or "").strip())


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Batch-judge stored quality snapshots")
    parser.add_argument("--limit", type=int, default=25, help="Max events to judge this run")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not has_gemini_key():
        print(_SKIP_NO_KEY)
        return 0
    limit = max(1, int(args.limit))
    stats = asyncio.run(run_batch(limit=limit))
    print(
        "online judge finished: "
        f"considered={stats['considered']} written={stats['written']} "
        f"skipped={stats['skipped']} errors={stats['errors']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
