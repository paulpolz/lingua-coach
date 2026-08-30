"""Unit tests for evals.mine — mocked rows, no Postgres, no Gemini."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import yaml

from evals.mine import (
    CLUSTER_TAGS,
    PLACEHOLDER_USER_MESSAGE,
    MineError,
    MineHit,
    dedupe_hits,
    hit_to_case,
    hits_from_jobs,
    hits_from_lessons,
    hits_from_mistakes,
    hits_from_quality_events,
    parse_args,
    resolve_database_url,
    stub_id,
    strip_pii,
    tag_hit,
    truncate_text,
    write_stubs,
)
from evals.run import GATED_SUITES, SUITE_DIRS, _suites_to_load


def test_strip_pii_redacts_email_and_uuid() -> None:
    uid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    raw = f"Contact me at learner@example.com about lesson {uid} please"
    cleaned = strip_pii(raw)
    assert "example.com" not in cleaned
    assert "[email]" in cleaned
    assert uid not in cleaned
    assert "[id]" in cleaned


def test_truncate_user_text() -> None:
    long = "x" * 400
    out = truncate_text(long, 40)
    assert len(out) <= 40
    assert out.endswith("…")


def test_tag_thumbs_down_and_immersion() -> None:
    tags = tag_hit(
        source="thumbs_down",
        text="The past tense of go is went. You should say fui.",
        target_language="es",
    )
    assert "thumbs_down" in tags
    assert "immersion" in tags
    assert tags == tuple(t for t in CLUSTER_TAGS if t in tags)


def test_tag_job_fail_schema() -> None:
    tags = tag_hit(source="job_fail", error="Pydantic validation: curriculum JSON parse failed")
    assert tags == ("schema", "job_fail")


def test_tag_too_hard_feedback() -> None:
    tags = tag_hit(source="learner_feedback", text="This was too hard and too fast")
    assert "user_too_hard" in tags


def test_hits_from_quality_events_filters_upvotes_and_high_csat() -> None:
    down = SimpleNamespace(
        id=uuid4(),
        kind="thumbs",
        surface="lesson",
        created_at=datetime.now(timezone.utc),
        value={"thumb": -1, "snapshot": {"assistant_text": "Hola.", "target": "es"}},
    )
    up = SimpleNamespace(
        id=uuid4(),
        kind="thumbs",
        surface="lesson",
        created_at=datetime.now(timezone.utc),
        value={"thumb": 1},
    )
    low = SimpleNamespace(
        id=uuid4(),
        kind="lesson_csat",
        surface="lesson",
        created_at=datetime.now(timezone.utc),
        value={"csat": 2},
    )
    high = SimpleNamespace(
        id=uuid4(),
        kind="lesson_csat",
        surface="lesson",
        created_at=datetime.now(timezone.utc),
        value={"csat": 5},
    )
    hits = hits_from_quality_events([down, up, low, high])
    sources = {h.source for h in hits}
    assert sources == {"thumbs_down", "low_csat"}
    assert all("thumbs_down" in h.tags for h in hits)


def test_hits_from_mistakes_requires_high_count_and_correction() -> None:
    stub = SimpleNamespace(
        id=uuid4(),
        user_id=uuid4(),
        pattern_type="articles",
        example_text="voy a tienda",
        correction="voy a la tienda",
        occurrence_count=5,
        last_seen_at=datetime.now(timezone.utc),
    )
    weak = SimpleNamespace(
        id=uuid4(),
        user_id=uuid4(),
        pattern_type="articles",
        example_text="voy a tienda",
        correction="voy a la tienda",
        occurrence_count=1,
        last_seen_at=datetime.now(timezone.utc),
    )
    no_fix = SimpleNamespace(
        id=uuid4(),
        user_id=uuid4(),
        pattern_type="articles",
        example_text="voy a tienda",
        correction=None,
        occurrence_count=9,
        last_seen_at=datetime.now(timezone.utc),
    )
    hits = hits_from_mistakes([stub, weak, no_fix], min_occurrences=3)
    assert len(hits) == 1
    assert hits[0].source == "stubborn_mistake"
    assert "user_too_hard" in hits[0].tags


def test_hits_from_lessons_and_jobs() -> None:
    lesson = SimpleNamespace(
        id=uuid4(),
        user_id=uuid4(),
        payload={"session_summary": {"learner_feedback": "too hard, more speaking"}},
        accomplished_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    empty = SimpleNamespace(
        id=uuid4(),
        user_id=uuid4(),
        payload={"session_summary": {"learner_feedback": ""}},
        accomplished_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    lesson_hits = hits_from_lessons([lesson, empty])
    assert len(lesson_hits) == 1
    assert "user_too_hard" in lesson_hits[0].tags

    job = SimpleNamespace(
        id=uuid4(),
        type="lesson_generate",
        status="failed",
        error="schema repair exhausted",
        created_at=datetime.now(timezone.utc),
    )
    job_hits = hits_from_jobs([job])
    assert len(job_hits) == 1
    assert job_hits[0].mode == "lesson_generation"
    assert "job_fail" in job_hits[0].tags
    assert "schema" in job_hits[0].tags


def test_stub_yaml_is_inbox_and_omits_transcript(tmp_path) -> None:
    hit = MineHit(
        source="thumbs_down",
        mode="lesson",
        tags=("immersion", "thumbs_down"),
        event_key="abcd1234",
        truncated_text="You should say the word because…",
        native="en",
        target="es",
        extra="quality_events thumbs-down",
    )
    case = hit_to_case(hit)
    assert case["id"] == stub_id(hit)
    assert case["suite"] == "inbox"
    assert case["mode"] == "lesson"
    assert case["input"]["user_message"] == PLACEHOLDER_USER_MESSAGE
    assert "suggested_checks" in case
    assert "no_english_learner_facing" in case["suggested_checks"]
    dumped = yaml.safe_dump(case)
    assert "learner@example.com" not in dumped
    assert case["input"]["user_message"] != hit.truncated_text
    assert len(hit.truncated_text) < 200

    written = write_stubs([hit], tmp_path, limit=20, dry_run=False)
    assert len(written) == 1
    loaded = yaml.safe_load(written[0].read_text(encoding="utf-8"))
    assert loaded["suite"] == "inbox"
    assert loaded["id"].startswith("inbox_")


def test_write_stubs_respects_limit_and_dry_run(tmp_path) -> None:
    hits = [
        MineHit(
            source="thumbs_down",
            mode="lesson",
            tags=("thumbs_down",),
            event_key=f"key{i:02d}",
            truncated_text="ok",
        )
        for i in range(5)
    ]
    assert write_stubs(hits, tmp_path, limit=2, dry_run=True) == []
    assert list(tmp_path.glob("*.yaml")) == []
    written = write_stubs(hits, tmp_path, limit=2, dry_run=False)
    assert len(written) == 2


def test_dedupe_keeps_newest() -> None:
    older = datetime(2026, 8, 1, tzinfo=timezone.utc)
    newer = datetime(2026, 8, 30, tzinfo=timezone.utc)
    a = MineHit(
        source="thumbs_down",
        mode="lesson",
        tags=("thumbs_down",),
        event_key="old",
        truncated_text="same snippet",
        created_at=older,
    )
    b = MineHit(
        source="thumbs_down",
        mode="lesson",
        tags=("thumbs_down",),
        event_key="new",
        truncated_text="same snippet",
        created_at=newer,
    )
    out = dedupe_hits([a, b])
    assert len(out) == 1
    assert out[0].event_key == "new"


def test_resolve_database_url_fails_when_missing() -> None:
    try:
        resolve_database_url(None, environ={})
    except MineError as exc:
        assert "DATABASE_URL" in str(exc)
        assert exc.code == 1
    else:
        raise AssertionError("expected MineError")


def test_resolve_database_url_prefers_cli_and_normalizes() -> None:
    url = resolve_database_url(
        "postgresql://lingua:lingua@localhost:5432/lingua_coach",
        environ={"DATABASE_URL": "ignored"},
    )
    assert url.startswith("postgresql+asyncpg://")


def test_parse_args_defaults() -> None:
    args = parse_args([])
    assert args.days == 7
    assert args.limit == 20
    assert args.dry_run is False
    assert args.out.endswith("cases/inbox")


def test_main_exits_when_database_url_missing(monkeypatch, capsys) -> None:
    from evals.mine import main

    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert main(["--dry-run"]) == 1
    err = capsys.readouterr().err
    assert "DATABASE_URL" in err


def test_regression_suite_does_not_load_inbox() -> None:
    assert _suites_to_load("regression") == ["regression"]
    assert _suites_to_load("all") == ["capability", "regression"]
    assert "inbox" not in GATED_SUITES
    assert SUITE_DIRS["inbox"] == "cases/inbox"
    assert SUITE_DIRS["regression"] == "cases/regression"
