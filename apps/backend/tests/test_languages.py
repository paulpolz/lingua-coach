"""Language-agnostic coaching contract (Wave 2).

Covers learner_profile.languages, normalize_language, persist columns,
GET /profile fields, lesson generation snapshot, and _lesson_profile_block.
"""

from __future__ import annotations

import copy
import json
import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy import select

from app.api.v1.chat import _lesson_profile_block, _persist_learner_profile
from app.models.learning_goal import LearningGoal
from app.models.learning_plan import LearningPlan
from app.models.enums import LearningGoalStatus, LearningPlanStatus
from app.models.profile import Profile
from app.models.user import User
from app.schemas.learner_profile import LearnerProfile
from app.schemas.roadmap import CourseRoadmap
from app.services.extraction import extract_learner_profile
from app.services.languages import language_policy_block, normalize_language
from app.services.lesson_generation import _build_generation_prompt, _profile_snapshot
from tests.fixtures import (
    VALID_COURSE_ROADMAP,
    VALID_LEARNER_PROFILE,
    VALID_LEARNER_PROFILE_ES,
    VALID_LESSON_CURRICULUM,
)


async def _sync_user(client: AsyncClient, as_principal, clerk_user_id: str) -> str:
    as_principal(clerk_user_id)
    resp = await client.post("/api/v1/auth/sync")
    assert resp.status_code == 200
    return resp.json()["user_id"]


def _fenced(marker: str, payload: dict) -> str:
    return f"```json:{marker}\n{json.dumps(payload)}\n```"


def _parse_sse(raw_text: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    for block in raw_text.strip().split("\n\n"):
        if not block.strip():
            continue
        lines = block.splitlines()
        event_name = next(line.removeprefix("event: ") for line in lines if line.startswith("event: "))
        data_line = next(line.removeprefix("data: ") for line in lines if line.startswith("data: "))
        events.append((event_name, json.loads(data_line)))
    return events


# --- Schema -----------------------------------------------------------------


def test_learner_profile_requires_languages_native_and_target() -> None:
    missing = copy.deepcopy(VALID_LEARNER_PROFILE)
    del missing["languages"]
    with pytest.raises(ValidationError):
        LearnerProfile.model_validate(missing)

    no_native = copy.deepcopy(VALID_LEARNER_PROFILE)
    del no_native["languages"]["native"]
    with pytest.raises(ValidationError):
        LearnerProfile.model_validate(no_native)

    no_target = copy.deepcopy(VALID_LEARNER_PROFILE)
    del no_target["languages"]["target"]
    with pytest.raises(ValidationError):
        LearnerProfile.model_validate(no_target)

    empty_native = copy.deepcopy(VALID_LEARNER_PROFILE)
    empty_native["languages"]["native"] = ""
    with pytest.raises(ValidationError):
        LearnerProfile.model_validate(empty_native)

    empty_target = copy.deepcopy(VALID_LEARNER_PROFILE)
    empty_target["languages"]["target"] = ""
    with pytest.raises(ValidationError):
        LearnerProfile.model_validate(empty_target)


def test_extract_learner_profile_without_languages_returns_none() -> None:
    bad = copy.deepcopy(VALID_LEARNER_PROFILE)
    del bad["languages"]
    assert extract_learner_profile("ok\n\n" + _fenced("learner_profile", bad)) is None


def test_course_roadmap_summary_keeps_target_language() -> None:
    roadmap = CourseRoadmap.model_validate(VALID_COURSE_ROADMAP)
    assert roadmap.summary.target_language == "en"
    assert roadmap.summary.native_language == "en"


# --- Normalizer -------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Spanish", "es"),
        ("es", "es"),
        ("español", "es"),
        ("ES", "es"),
        ("  Español  ", "es"),
    ],
)
def test_normalize_language_maps_spanish_aliases(raw: str, expected: str) -> None:
    assert normalize_language(raw) == expected


def test_normalize_language_stores_unknown_lowercase() -> None:
    assert normalize_language("Klingon") == "klingon"
    assert normalize_language("  Elvish  ") == "elvish"


# --- Persist + GET /profile -------------------------------------------------


async def test_persist_writes_native_target_and_level(
    client: AsyncClient, as_principal, mock_gemini, db_session
) -> None:
    user_id = await _sync_user(client, as_principal, "clerk_persist_languages")
    session_id = (await client.post("/api/v1/chat/sessions", json={"type": "onboarding"})).json()["id"]

    reply = "I have what I need!\n\n" + _fenced("learner_profile", VALID_LEARNER_PROFILE)
    mock_gemini([reply])

    async with client.stream(
        "POST",
        f"/api/v1/chat/sessions/{session_id}/messages",
        json={"content": "Here's my situation..."},
    ) as resp:
        async for _ in resp.aiter_text():
            pass

    profile = (
        await db_session.execute(select(Profile).where(Profile.user_id == uuid.UUID(user_id)))
    ).scalar_one()
    assert profile.native_language == "en"
    assert profile.target_language == "en"
    assert profile.target_level == VALID_LEARNER_PROFILE["level"]["self_assessed"]
    assert "english_level" not in Profile.__table__.c
    assert "target_level" in Profile.__table__.c


async def test_persist_normalizes_language_aliases_and_unknown(
    client: AsyncClient, as_principal, db_session
) -> None:
    user_id = await _sync_user(client, as_principal, "clerk_persist_aliases")
    user = await db_session.get(User, uuid.UUID(user_id))
    assert user is not None

    aliased = copy.deepcopy(VALID_LEARNER_PROFILE)
    aliased["languages"] = {"native": "English", "target": "español"}
    await _persist_learner_profile(db_session, user, LearnerProfile.model_validate(aliased))

    profile = (
        await db_session.execute(select(Profile).where(Profile.user_id == user.id))
    ).scalar_one()
    assert profile.native_language == "en"
    assert profile.target_language == "es"
    assert profile.target_level == aliased["level"]["self_assessed"]

    unknown = copy.deepcopy(VALID_LEARNER_PROFILE)
    unknown["languages"] = {"native": "Klingon", "target": "Spanish"}
    await _persist_learner_profile(db_session, user, LearnerProfile.model_validate(unknown))

    await db_session.refresh(profile)
    assert profile.native_language == "klingon"
    assert profile.target_language == "es"


async def test_valid_learner_profile_es_round_trip(
    client: AsyncClient, as_principal, mock_gemini, db_session
) -> None:
    user_id = await _sync_user(client, as_principal, "clerk_es_roundtrip")
    session_id = (await client.post("/api/v1/chat/sessions", json={"type": "onboarding"})).json()["id"]

    reply = "Listo.\n\n" + _fenced("learner_profile", VALID_LEARNER_PROFILE_ES)
    mock_gemini([reply])

    async with client.stream(
        "POST",
        f"/api/v1/chat/sessions/{session_id}/messages",
        json={"content": "Mi situación..."},
    ) as resp:
        raw = ""
        async for chunk in resp.aiter_text():
            raw += chunk

    done_data = next(e[1] for e in _parse_sse(raw) if e[0] == "done")
    assert "json:learner_profile" not in done_data["content"]
    assert (
        done_data["metadata"]["plan_updates"]["goal_summary"]
        == VALID_LEARNER_PROFILE_ES["goal"]["outcome"]
    )

    profile = (
        await db_session.execute(select(Profile).where(Profile.user_id == uuid.UUID(user_id)))
    ).scalar_one()
    assert profile.native_language == "en"
    assert profile.target_language == "es"
    assert profile.target_level == VALID_LEARNER_PROFILE_ES["level"]["self_assessed"]
    assert profile.goal_outcome == VALID_LEARNER_PROFILE_ES["goal"]["outcome"]

    body = (await client.get("/api/v1/profile")).json()
    assert body["native_language"] == "en"
    assert body["target_language"] == "es"
    assert body["level"] == VALID_LEARNER_PROFILE_ES["level"]["self_assessed"]
    assert body["goal_summary"] == VALID_LEARNER_PROFILE_ES["goal"]["outcome"]


async def test_profile_get_exposes_language_fields_after_interview(
    client: AsyncClient, as_principal, mock_gemini
) -> None:
    await _sync_user(client, as_principal, "clerk_profile_languages_get")
    session_id = (await client.post("/api/v1/chat/sessions", json={"type": "onboarding"})).json()["id"]
    mock_gemini(["Got it!\n\n" + _fenced("learner_profile", VALID_LEARNER_PROFILE)])

    async with client.stream(
        "POST",
        f"/api/v1/chat/sessions/{session_id}/messages",
        json={"content": "my situation"},
    ) as resp:
        async for _ in resp.aiter_text():
            pass

    body = (await client.get("/api/v1/profile")).json()
    assert "native_language" in body
    assert "target_language" in body
    assert body["native_language"] == "en"
    assert body["target_language"] == "en"
    assert body["level"] == VALID_LEARNER_PROFILE["level"]["self_assessed"]
    assert "english_level" not in body


# --- Lesson generation snapshot + lesson profile block ----------------------


def test_profile_snapshot_includes_language_pair() -> None:
    profile = Profile(
        user_id=uuid.uuid4(),
        native_language="en",
        target_language="es",
        target_level="B1",
        goal_outcome="Hablar con confianza",
    )
    snap = _profile_snapshot(profile)
    assert snap is not None
    assert snap["native_language"] == "en"
    assert snap["target_language"] == "es"
    assert snap["target_level"] == "B1"
    assert "english_level" not in snap


async def test_lesson_generation_prompt_includes_language_pair(
    client: AsyncClient, as_principal, db_session
) -> None:
    user_id = await _sync_user(client, as_principal, "clerk_gen_snapshot_langs")
    user = await db_session.get(User, uuid.UUID(user_id))
    assert user is not None
    user.onboarding_complete = True
    goal = LearningGoal(
        user_id=user.id,
        goal_statement=VALID_LEARNER_PROFILE_ES["goal"]["outcome"],
        status=LearningGoalStatus.active,
    )
    db_session.add(goal)
    await db_session.flush()
    db_session.add(
        LearningPlan(
            user_id=user.id,
            learning_goal_id=goal.id,
            status=LearningPlanStatus.accepted,
            roadmap=VALID_COURSE_ROADMAP,
            current_milestone_index=0,
            accepted_at=datetime.now(timezone.utc),
        )
    )
    db_session.add(
        Profile(
            user_id=user.id,
            native_language="en",
            target_language="es",
            target_level="B1",
            goal_outcome=VALID_LEARNER_PROFILE_ES["goal"]["outcome"],
        )
    )
    await db_session.commit()

    prompt, native, target = await _build_generation_prompt(
        db_session, user_id=user.id, lesson_number=1
    )
    assert native == "en"
    assert target == "es"
    assert '"native_language": "en"' in prompt
    assert '"target_language": "es"' in prompt
    assert '"target_level": "B1"' in prompt
    assert "english_level" not in prompt


async def test_lesson_profile_block_includes_language_pair(
    client: AsyncClient, as_principal, db_session
) -> None:
    user_id = await _sync_user(client, as_principal, "clerk_lesson_block_langs")
    user = await db_session.get(User, uuid.UUID(user_id))
    assert user is not None
    db_session.add(
        Profile(
            user_id=user.id,
            native_language="en",
            target_language="es",
            target_level="B1",
            goal_outcome="Hablar con confianza",
        )
    )
    await db_session.commit()

    block = await _lesson_profile_block(db_session, user)
    assert "Native language: en" in block
    assert "Target language: es" in block
    assert "Conduct this lesson only in es." in block
    assert "Level: B1" in block


async def test_lesson_generation_policy_block_includes_pair(
    client: AsyncClient, as_principal, db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict = {}

    async def _fake_generate_json(*, system_instruction: str, history: list, **_kw) -> str:
        captured["system_instruction"] = system_instruction
        captured["history"] = history
        return json.dumps(VALID_LESSON_CURRICULUM)

    monkeypatch.setattr("app.services.gemini.generate_json", _fake_generate_json)

    user_id = await _sync_user(client, as_principal, "clerk_gen_policy_langs")
    user = await db_session.get(User, uuid.UUID(user_id))
    assert user is not None
    user.onboarding_complete = True
    goal = LearningGoal(
        user_id=user.id,
        goal_statement="Hablar",
        status=LearningGoalStatus.active,
    )
    db_session.add(goal)
    await db_session.flush()
    plan = LearningPlan(
        user_id=user.id,
        learning_goal_id=goal.id,
        status=LearningPlanStatus.accepted,
        roadmap=VALID_COURSE_ROADMAP,
        current_milestone_index=0,
        accepted_at=datetime.now(timezone.utc),
    )
    db_session.add(plan)
    db_session.add(
        Profile(
            user_id=user.id,
            native_language="en",
            target_language="es",
            target_level="B1",
        )
    )
    await db_session.commit()

    start_resp = await client.post("/api/v1/lessons/start")
    assert start_resp.status_code == 202
    assert "Native: en / Target: es" in captured["system_instruction"]
    assert "Write the entire curriculum in es" in captured["system_instruction"]


def test_language_policy_block_onboarding_unknown_starts_in_english() -> None:
    block = language_policy_block(surface="onboarding")
    assert "Start this interview in English" in block
    assert "languages.native" in block
    assert "languages.target" in block


def test_language_policy_block_lesson_uses_target() -> None:
    block = language_policy_block(surface="lesson", native="en", target="ja")
    assert "Native: en / Target: ja" in block
    assert "Conduct this lesson only in ja" in block
