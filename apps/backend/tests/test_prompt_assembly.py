from __future__ import annotations

import json

from app.services.languages import language_policy_block
from app.services.prompt_assembly import (
    build_generation_user_prompt,
    lesson_curriculum_snippet_from_payload,
    lesson_generation_system_instruction,
    lesson_profile_block_from_snapshot,
    lesson_system_instruction,
    onboarding_system_instruction,
)
from app.services.skills import (
    LESSON_EXTRACTION_CONTRACT,
    LESSON_GENERATION_CONTRACT,
    ONBOARDING_EXTRACTION_CONTRACT,
    get_system_instruction,
)
from tests.fixtures import VALID_LESSON_CURRICULUM


def test_onboarding_system_instruction_is_skills_then_contract_then_policy() -> None:
    native, target = "en", "es"
    text = onboarding_system_instruction(native, target)
    skills = get_system_instruction("onboarding")
    policy = language_policy_block(surface="onboarding", native=native, target=target)
    assert text == f"{skills}\n\n{ONBOARDING_EXTRACTION_CONTRACT}\n\n{policy}"


def test_lesson_system_instruction_parity_with_and_without_vocab() -> None:
    native, target = "en", "es"
    without = lesson_system_instruction(native, target, False)
    with_vocab = lesson_system_instruction(native, target, True)
    policy = language_policy_block(surface="lesson", native=native, target=target)
    assert without == (
        f"{get_system_instruction('lesson', include_vocab_formats=False)}\n\n"
        f"{LESSON_EXTRACTION_CONTRACT}\n\n{policy}"
    )
    assert with_vocab == (
        f"{get_system_instruction('lesson', include_vocab_formats=True)}\n\n"
        f"{LESSON_EXTRACTION_CONTRACT}\n\n{policy}"
    )
    assert with_vocab != without
    assert len(with_vocab) > len(without)


def test_lesson_generation_system_instruction_parity() -> None:
    native, target = "en", "es"
    text = lesson_generation_system_instruction(native, target)
    policy = language_policy_block(
        surface="lesson_generation", native=native, target=target
    )
    assert text == (
        f"{get_system_instruction('lesson')}\n\n{LESSON_GENERATION_CONTRACT}\n\n{policy}"
    )


def test_curriculum_snippet_empty_and_populated_match_chat_strings() -> None:
    assert lesson_curriculum_snippet_from_payload({}) == (
        "Current lesson curriculum: not yet generated (lesson is still generating)."
    )
    assert lesson_curriculum_snippet_from_payload(None) == (
        "Current lesson curriculum: not yet generated (lesson is still generating)."
    )
    snippet = lesson_curriculum_snippet_from_payload(VALID_LESSON_CURRICULUM)
    assert snippet.startswith("Current lesson curriculum (lessons.payload.curriculum):")
    assert f"Lesson goal: {VALID_LESSON_CURRICULUM['lesson_goal']}" in snippet
    assert f"Grammar focus: {VALID_LESSON_CURRICULUM['grammar_focus']}" in snippet
    assert "  - warmup: Active recall — past tense timelines" in snippet
    assert "  - Produce 5 sentences with past simple + time marker" in snippet


def test_profile_block_from_snapshot_matches_chat_format() -> None:
    empty = lesson_profile_block_from_snapshot("en", "es", "Hablar", "B1", [])
    assert empty == (
        "Learner profile (compact):\n"
        "Native language: en\n"
        "Target language: es\n"
        "Goal: Hablar\n"
        "Level: B1\n"
        "Conduct this lesson only in es.\n"
        "Weak patterns due for review:\n"
        "  (none due)"
    )
    with_row = lesson_profile_block_from_snapshot(
        "en",
        "es",
        "Hablar",
        "B1",
        [{"pattern_type": "missing articles", "example_text": "voy a tienda"}],
    )
    assert "  - missing articles: voy a tienda" in with_row
    defaults = lesson_profile_block_from_snapshot(None, None, None, None, None)
    assert "Native language: (not set)" in defaults
    assert "Target language: en" in defaults
    assert "Conduct this lesson only in en." in defaults


def test_build_generation_user_prompt_wraps_json_context() -> None:
    context = {
        "lesson_number": 1,
        "active_plan": {"roadmap": None, "current_milestone_index": 0},
        "learner_profile": {"native_language": "en", "target_language": "es"},
        "prior_lessons": [],
        "open_mistakes": [],
    }
    prompt = build_generation_user_prompt(context)
    assert prompt == (
        "Generate the next lesson's curriculum for this learner, per the "
        "Generation rules above. Learner and plan context (JSON):\n"
        f"{json.dumps(context, default=str)}\n\n"
        "Pick one grammar focus and one vocab theme aligned to the current "
        "milestone; interleave due items from open_mistakes and prior_lessons "
        "before adding new material."
    )
    assert '"native_language": "en"' in prompt
    assert '"target_language": "es"' in prompt
