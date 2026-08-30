"""Mine production tutor-failure signals into ungated inbox YAML stubs.

SQL + rules only — no LLM. Inbox is not a ship gate: `--suite regression`
does not load `evals/cases/inbox/`.

From the repo root:

    PYTHONPATH=apps/backend:. python -m evals.mine
    PYTHONPATH=apps/backend:. python -m evals.mine --days 7 --limit 20 --dry-run

Needs `--database-url` or env `DATABASE_URL` (same as the backend). Missing
URL or an unreachable database exits non-zero. `--dry-run` prints counts and
does not write files.

`llm_retries` and structured log events (`lesson_generation_failed`,
`db_persist_failed`) are not in SQL — skipped on purpose.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import urlparse, urlunparse
from uuid import UUID

try:
    import yaml
except ImportError as exc:  # pragma: no cover - dependency hint
    raise SystemExit(
        "PyYAML is required. Install backend dev extras: "
        "`cd apps/backend && uv sync --extra dev`"
    ) from exc

EVALS_ROOT = Path(__file__).resolve().parent
REPO_ROOT = EVALS_ROOT.parent

if str(REPO_ROOT / "apps" / "backend") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "apps" / "backend"))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.exc import DBAPIError, OperationalError, ProgrammingError  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402

from app.models.enums import JobStatus  # noqa: E402
from app.models.job import Job  # noqa: E402
from app.models.lesson import Lesson  # noqa: E402
from app.models.mistake import Mistake  # noqa: E402
from app.models.profile import Profile  # noqa: E402
from app.models.quality_event import QualityEvent  # noqa: E402
from app.services.quality import KIND_LESSON_CSAT, KIND_THUMBS  # noqa: E402
from evals.checks import CheckContext, check_no_english_learner_facing  # noqa: E402

TEXT_MAX = 160
NOTES_MAX = 600
STUBBORN_OCCURRENCE_MIN = 3
LOW_CSAT_MAX = 2
PLACEHOLDER_USER_MESSAGE = "<fill on promote>"
DEFAULT_FIXTURE = "fixtures/learner_a2_travel_es.json"

CLUSTER_TAGS = ("immersion", "schema", "user_too_hard", "job_fail", "thumbs_down")

_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")
_UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)

_TOO_HARD_HINTS = (
    "too hard",
    "too difficult",
    "too fast",
    "too advanced",
    "over my head",
    "couldn't follow",
    "could not follow",
    "muy difícil",
    "demasiado difícil",
    "too much",
)
_IMMERSION_HINTS = (
    "wrong language",
    "in english",
    "spoke english",
    "not in spanish",
    "not spanish",
    "switched to english",
    "explain in english",
    "l1 leak",
    "native language",
)
_SCHEMA_HINTS = (
    "schema",
    "json",
    "parse",
    "pydantic",
    "validation",
    "repair",
    "invalid",
    "lesson_turn",
    "truncated",
    "curriculum",
)

_MODE_SKILL = {
    "onboarding": "onboarding_interviewer",
    "lesson": "exercise_tutor",
    "lesson_generation": "exercise_tutor",
}


class MineError(Exception):
    """Fatal miner error with a process exit code."""

    def __init__(self, message: str, *, code: int = 1) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class MineHit:
    source: str
    mode: str
    tags: tuple[str, ...]
    event_key: str
    truncated_text: str
    created_at: datetime | None = None
    native: str | None = None
    target: str | None = None
    extra: str = ""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Mine quality_events, finish feedback, failed jobs, and stubborn "
            "mistakes into evals/cases/inbox YAML stubs (not a ship gate)."
        )
    )
    parser.add_argument("--days", type=int, default=7, help="Lookback window (default 7).")
    parser.add_argument(
        "--out",
        default="evals/cases/inbox",
        help="Directory for inbox stubs (default: evals/cases/inbox).",
    )
    parser.add_argument("--limit", type=int, default=20, help="Max stubs to write (default 20).")
    parser.add_argument(
        "--database-url",
        default=None,
        help="Postgres URL. Required if DATABASE_URL is not set. No silent localhost default.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print source/tag counts; do not write YAML.",
    )
    parser.add_argument(
        "--min-occurrences",
        type=int,
        default=STUBBORN_OCCURRENCE_MIN,
        help="Mistake occurrence_count threshold (default 3).",
    )
    return parser.parse_args(argv)


def resolve_database_url(cli_url: str | None, environ: dict[str, str] | None = None) -> str:
    """Require an explicit URL. Do not fall back to Settings.database_url."""
    if cli_url and cli_url.strip():
        return _normalize_async_url(cli_url.strip())
    env = environ if environ is not None else os.environ
    from_env = (env.get("DATABASE_URL") or "").strip()
    if from_env:
        return _normalize_async_url(from_env)
    raise MineError(
        "DATABASE_URL is required. Pass --database-url or set the DATABASE_URL "
        "environment variable (same as the backend). Refusing to use a silent "
        "localhost default."
    )


def _normalize_async_url(url: str) -> str:
    if url.startswith("postgresql+asyncpg://") or url.startswith("postgres+asyncpg://"):
        return url
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url[len("postgresql://") :]
    if url.startswith("postgres://"):
        return "postgresql+asyncpg://" + url[len("postgres://") :]
    return url


def redact_database_url(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.password:
        return url
    user = parsed.username or ""
    host = parsed.hostname or ""
    netloc = f"{user}:***@{host}"
    if parsed.port:
        netloc += f":{parsed.port}"
    return urlunparse(parsed._replace(netloc=netloc))


def strip_pii(text: str | None) -> str:
    if not text:
        return ""
    cleaned = _EMAIL_RE.sub("[email]", str(text))
    cleaned = _UUID_RE.sub("[id]", cleaned)
    return cleaned


def truncate_text(text: str | None, limit: int = TEXT_MAX) -> str:
    cleaned = strip_pii(text).replace("\n", " ").strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "…"


def _contains_any(blob: str, hints: Sequence[str]) -> bool:
    return any(hint in blob for hint in hints)


def _assistant_looks_like_l1_leak(assistant_text: str, target: str | None) -> bool:
    if not (assistant_text or "").strip() or not (target or "").strip():
        return False
    ctx = CheckContext(
        raw_completion=assistant_text,
        locale_native=None,
        locale_target=target,
        fixture={},
        mode="lesson",
    )
    return not check_no_english_learner_facing(ctx).passed


def tag_hit(
    *,
    source: str,
    text: str = "",
    error: str = "",
    target_language: str | None = None,
    csat: int | None = None,
) -> tuple[str, ...]:
    """Crude keyword / check tags. No LLM."""
    blob = f"{text} {error}".lower()
    tags: list[str] = []
    if source in {"thumbs_down", "low_csat"}:
        tags.append("thumbs_down")
    if source == "job_fail":
        tags.append("job_fail")
    if source == "stubborn_mistake" or _contains_any(blob, _TOO_HARD_HINTS):
        tags.append("user_too_hard")
    if csat is not None and csat <= 1:
        if "user_too_hard" not in tags:
            tags.append("user_too_hard")
    if _contains_any(blob, _IMMERSION_HINTS) or _assistant_looks_like_l1_leak(
        text, target_language
    ):
        tags.append("immersion")
    if source == "job_fail" or _contains_any(blob, _SCHEMA_HINTS):
        tags.append("schema")
    # Preserve spec order, unique.
    ordered = tuple(tag for tag in CLUSTER_TAGS if tag in tags)
    return ordered


def _mode_from_surface(surface: str | None) -> str:
    if surface in {"onboarding", "lesson", "lesson_generation"}:
        return surface
    return "lesson"


def _short_key(value: Any) -> str:
    if isinstance(value, UUID):
        return value.hex[:8]
    raw = str(value or "")
    if not raw:
        return hashlib.sha1(b"empty").hexdigest()[:8]
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]


def _profile_locale(profile: Profile | None) -> tuple[str | None, str | None]:
    if profile is None:
        return None, None
    native = profile.native_language or None
    target = profile.target_language or None
    return native, target


def hits_from_quality_events(events: Sequence[Any]) -> list[MineHit]:
    hits: list[MineHit] = []
    for event in events:
        value = event.value if isinstance(getattr(event, "value", None), dict) else {}
        kind = getattr(event, "kind", None)
        snapshot = value.get("snapshot") if isinstance(value.get("snapshot"), dict) else {}
        assistant = str(snapshot.get("assistant_text") or "")
        native = snapshot.get("native") if isinstance(snapshot.get("native"), str) else None
        target = snapshot.get("target") if isinstance(snapshot.get("target"), str) else None
        mode = _mode_from_surface(getattr(event, "surface", None))
        created = getattr(event, "created_at", None)

        if kind == KIND_THUMBS:
            if value.get("thumb") != -1:
                continue
            source = "thumbs_down"
            tags = tag_hit(source=source, text=assistant, target_language=target)
            extra = "quality_events thumbs-down"
        elif kind == KIND_LESSON_CSAT:
            try:
                csat_n = int(value.get("csat"))
            except (TypeError, ValueError):
                continue
            if csat_n > LOW_CSAT_MAX:
                continue
            source = "low_csat"
            tags = tag_hit(source=source, text=assistant, target_language=target, csat=csat_n)
            extra = f"quality_events lesson_csat={csat_n}"
        else:
            continue

        hits.append(
            MineHit(
                source=source,
                mode=mode,
                tags=tags,
                event_key=_short_key(getattr(event, "id", None)),
                truncated_text=truncate_text(assistant),
                created_at=created,
                native=native,
                target=target,
                extra=extra,
            )
        )
    return hits


def _lesson_feedback(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    summary = payload.get("session_summary")
    if not isinstance(summary, dict):
        return ""
    raw = summary.get("learner_feedback")
    if raw is None:
        return ""
    return str(raw).strip()


def hits_from_lessons(
    lessons: Sequence[Any],
    profiles: dict[Any, Profile] | None = None,
) -> list[MineHit]:
    profiles = profiles or {}
    hits: list[MineHit] = []
    for lesson in lessons:
        feedback = _lesson_feedback(getattr(lesson, "payload", None))
        if not feedback:
            continue
        native, target = _profile_locale(profiles.get(getattr(lesson, "user_id", None)))
        tags = tag_hit(source="learner_feedback", text=feedback, target_language=target)
        hits.append(
            MineHit(
                source="learner_feedback",
                mode="lesson",
                tags=tags,
                event_key=_short_key(getattr(lesson, "id", None)),
                truncated_text=truncate_text(feedback),
                created_at=getattr(lesson, "accomplished_at", None)
                or getattr(lesson, "updated_at", None),
                native=native,
                target=target,
                extra="lessons.payload.session_summary.learner_feedback",
            )
        )
    return hits


def hits_from_jobs(jobs: Sequence[Any]) -> list[MineHit]:
    hits: list[MineHit] = []
    for job in jobs:
        status = getattr(job, "status", None)
        if status != JobStatus.failed and str(status) != "failed":
            continue
        error = str(getattr(job, "error", None) or "")
        job_type = str(getattr(job, "type", "") or "")
        mode = "lesson_generation" if "generate" in job_type else "lesson"
        tags = tag_hit(source="job_fail", error=error)
        hits.append(
            MineHit(
                source="job_fail",
                mode=mode,
                tags=tags,
                event_key=_short_key(getattr(job, "id", None)),
                truncated_text=truncate_text(error),
                created_at=getattr(job, "created_at", None),
                extra=f"jobs.status=failed type={truncate_text(job_type, 40)}",
            )
        )
    return hits


def hits_from_mistakes(
    mistakes: Sequence[Any],
    *,
    min_occurrences: int = STUBBORN_OCCURRENCE_MIN,
    profiles: dict[Any, Profile] | None = None,
) -> list[MineHit]:
    profiles = profiles or {}
    hits: list[MineHit] = []
    for mistake in mistakes:
        count = int(getattr(mistake, "occurrence_count", 0) or 0)
        correction = str(getattr(mistake, "correction", None) or "").strip()
        if count < min_occurrences or not correction:
            continue
        native, target = _profile_locale(profiles.get(getattr(mistake, "user_id", None)))
        pattern = str(getattr(mistake, "pattern_type", "") or "")
        snippet = f"{pattern}: {correction}"
        tags = tag_hit(source="stubborn_mistake", text=snippet, target_language=target)
        hits.append(
            MineHit(
                source="stubborn_mistake",
                mode="lesson",
                tags=tags,
                event_key=_short_key(getattr(mistake, "id", None)),
                truncated_text=truncate_text(snippet),
                created_at=getattr(mistake, "last_seen_at", None),
                native=native,
                target=target,
                extra=f"mistakes.occurrence_count={count} same correction",
            )
        )
    return hits


def cluster_counts(hits: Sequence[MineHit]) -> dict[str, int]:
    counts = {tag: 0 for tag in CLUSTER_TAGS}
    untagged = 0
    for hit in hits:
        if not hit.tags:
            untagged += 1
            continue
        for tag in hit.tags:
            counts[tag] = counts.get(tag, 0) + 1
    if untagged:
        counts["untagged"] = untagged
    return counts


def source_counts(hits: Sequence[MineHit]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for hit in hits:
        counts[hit.source] = counts.get(hit.source, 0) + 1
    return counts


def _sort_ts(hit: MineHit) -> datetime:
    ts = hit.created_at
    if ts is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts


def dedupe_hits(hits: Sequence[MineHit]) -> list[MineHit]:
    """Keep the newest hit per (source, mode, tags, truncated_text prefix)."""
    ranked = sorted(hits, key=_sort_ts, reverse=True)
    seen: set[tuple[str, str, tuple[str, ...], str]] = set()
    out: list[MineHit] = []
    for hit in ranked:
        key = (hit.source, hit.mode, hit.tags, hit.truncated_text[:80])
        if key in seen:
            continue
        seen.add(key)
        out.append(hit)
    return out


def _primary_slug(hit: MineHit) -> str:
    for tag in CLUSTER_TAGS:
        if tag in hit.tags:
            return tag
    return hit.source


def stub_id(hit: MineHit) -> str:
    return f"inbox_{_primary_slug(hit)}_{hit.mode}_{hit.event_key}"


def suggested_checks(hit: MineHit) -> list[str]:
    checks: list[str] = []
    if hit.mode == "lesson":
        checks.append("extract_lesson_turn")
        if "immersion" in hit.tags:
            checks.append("no_english_learner_facing")
    elif hit.mode == "lesson_generation":
        checks.extend(
            [
                "curriculum_valid",
                "invented_milestone",
                "exit_criteria_nonempty_unique",
            ]
        )
        if "immersion" in hit.tags:
            checks.append("no_english_learner_facing")
    elif hit.mode == "onboarding":
        checks.extend(["extract_learner_profile", "one_question_rule"])
    seen: set[str] = set()
    unique: list[str] = []
    for name in checks:
        if name not in seen:
            seen.add(name)
            unique.append(name)
    return unique


def hit_to_case(hit: MineHit) -> dict[str, Any]:
    notes = (
        "Inbox stub from evals.mine — NOT a ship gate. Do not commit until "
        "promoted. Copy to evals/cases/regression/ after stripping remaining "
        "PII, writing expected checks, and adding fixtures/replay/<id>.json.\n"
        f"Source: {hit.source}. {hit.extra}.\n"
        f"Tags: {', '.join(hit.tags) if hit.tags else 'none'}.\n"
    )
    if hit.truncated_text:
        notes += f"Truncated snippet: {hit.truncated_text}\n"
    notes = truncate_text(notes, NOTES_MAX)

    case: dict[str, Any] = {
        "id": stub_id(hit),
        "suite": "inbox",
        "mode": hit.mode,
        "skill": _MODE_SKILL.get(hit.mode, "exercise_tutor"),
        "input": {
            "system_from_skills": True,
            "context_fixture": DEFAULT_FIXTURE,
            "user_message": PLACEHOLDER_USER_MESSAGE,
        },
        "checks": {"deterministic": []},
        "suggested_checks": suggested_checks(hit),
        "notes": notes,
    }
    locale: dict[str, str] = {}
    if hit.native:
        locale["native"] = str(hit.native)
    if hit.target:
        locale["target"] = str(hit.target)
    if locale:
        case["locale"] = locale
    return case


def write_stubs(
    hits: Sequence[MineHit],
    out_dir: Path,
    *,
    limit: int,
    dry_run: bool,
) -> list[Path]:
    chosen = list(hits)[: max(0, limit)]
    if dry_run or not chosen:
        return []
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for hit in chosen:
        case = hit_to_case(hit)
        path = out_dir / f"{case['id']}.yaml"
        path.write_text(
            yaml.safe_dump(case, sort_keys=False, allow_unicode=True, default_flow_style=False),
            encoding="utf-8",
        )
        written.append(path)
    return written


def format_summary(
    *,
    days: int,
    hits: Sequence[MineHit],
    deduped: Sequence[MineHit],
    written: Sequence[Path],
    dry_run: bool,
    out_dir: Path,
    limit: int,
) -> str:
    src = source_counts(hits)
    tags = cluster_counts(hits)
    lines = [
        f"mined {len(hits)} hit(s) over last {days} day(s) "
        f"({len(deduped)} after dedupe, limit {limit}).",
        "sources: "
        + (
            ", ".join(f"{name}={count}" for name, count in sorted(src.items()))
            or "none"
        ),
        "tags: "
        + ", ".join(f"{name}={tags.get(name, 0)}" for name in CLUSTER_TAGS)
        + (f", untagged={tags['untagged']}" if "untagged" in tags else ""),
        "skipped llm_retries / structured logs (not in SQL).",
    ]
    if dry_run:
        lines.append(f"dry-run: would write {min(len(deduped), max(0, limit))} stub(s) to {out_dir}")
    else:
        lines.append(f"wrote {len(written)} stub(s) under {out_dir}")
        for path in written:
            lines.append(f"  {path.relative_to(REPO_ROOT) if path.is_relative_to(REPO_ROOT) else path}")
    return "\n".join(lines)


def _since(days: int) -> datetime:
    window = max(1, int(days))
    return datetime.now(timezone.utc) - timedelta(days=window)


async def _profile_map(db: AsyncSession, user_ids: set[Any]) -> dict[Any, Profile]:
    ids = {uid for uid in user_ids if uid is not None}
    if not ids:
        return {}
    result = await db.execute(select(Profile).where(Profile.user_id.in_(ids)))
    return {row.user_id: row for row in result.scalars().all()}


async def collect_hits(
    db: AsyncSession,
    *,
    since: datetime,
    min_occurrences: int,
) -> list[MineHit]:
    quality_rows = (
        (
            await db.execute(
                select(QualityEvent)
                .where(
                    QualityEvent.kind.in_((KIND_THUMBS, KIND_LESSON_CSAT)),
                    QualityEvent.created_at >= since,
                )
                .order_by(QualityEvent.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    lesson_rows = (
        (
            await db.execute(
                select(Lesson)
                .where(
                    Lesson.accomplished_at.is_not(None),
                    Lesson.accomplished_at >= since,
                )
                .order_by(Lesson.accomplished_at.desc())
            )
        )
        .scalars()
        .all()
    )
    job_rows = (
        (
            await db.execute(
                select(Job)
                .where(Job.status == JobStatus.failed, Job.created_at >= since)
                .order_by(Job.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    mistake_rows = (
        (
            await db.execute(
                select(Mistake)
                .where(
                    Mistake.occurrence_count >= min_occurrences,
                    Mistake.correction.is_not(None),
                    Mistake.last_seen_at >= since,
                )
                .order_by(Mistake.last_seen_at.desc())
            )
        )
        .scalars()
        .all()
    )

    user_ids = {getattr(row, "user_id", None) for row in (*lesson_rows, *mistake_rows)}
    profiles = await _profile_map(db, user_ids)

    hits: list[MineHit] = []
    hits.extend(hits_from_quality_events(quality_rows))
    hits.extend(hits_from_lessons(lesson_rows, profiles))
    hits.extend(hits_from_jobs(job_rows))
    hits.extend(hits_from_mistakes(mistake_rows, min_occurrences=min_occurrences, profiles=profiles))
    return hits


async def run_mine(
    *,
    database_url: str,
    days: int,
    out_dir: Path,
    limit: int,
    dry_run: bool,
    min_occurrences: int,
) -> tuple[list[MineHit], list[MineHit], list[Path]]:
    engine = create_async_engine(database_url, pool_pre_ping=True, future=True)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    redacted = redact_database_url(database_url)
    try:
        async with factory() as db:
            try:
                await db.execute(select(1))
                hits = await collect_hits(
                    db, since=_since(days), min_occurrences=min_occurrences
                )
            except ProgrammingError as exc:
                raise MineError(
                    "Database schema is missing a miner table (need quality_events "
                    "revision a8f3c1d92e4b plus jobs/lessons/mistakes). "
                    f"Run alembic upgrade head. Detail: {exc}"
                ) from exc
            except (OperationalError, OSError, DBAPIError) as exc:
                raise MineError(
                    f"Could not reach the database at {redacted}: {exc}"
                ) from exc
    except (OperationalError, OSError, DBAPIError) as exc:
        raise MineError(f"Could not reach the database at {redacted}: {exc}") from exc
    finally:
        await engine.dispose()

    deduped = dedupe_hits(hits)
    written = write_stubs(deduped, out_dir, limit=limit, dry_run=dry_run)
    return hits, deduped, written


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        url = resolve_database_url(args.database_url)
        out_dir = Path(args.out)
        if not out_dir.is_absolute():
            out_dir = REPO_ROOT / out_dir
        hits, deduped, written = asyncio.run(
            run_mine(
                database_url=url,
                days=int(args.days),
                out_dir=out_dir,
                limit=int(args.limit),
                dry_run=bool(args.dry_run),
                min_occurrences=int(args.min_occurrences),
            )
        )
    except MineError as exc:
        print(str(exc), file=sys.stderr)
        return exc.code
    print(
        format_summary(
            days=int(args.days),
            hits=hits,
            deduped=deduped,
            written=written,
            dry_run=bool(args.dry_run),
            out_dir=out_dir,
            limit=int(args.limit),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
