"""Builds Gemini system instructions and context turns. Pedagogy lives in skills/*.md."""

from __future__ import annotations

import json

from app.services.skills import (
    LESSON_EXTRACTION_CONTRACT,
    LESSON_GENERATION_CONTRACT,
    ONBOARDING_EXTRACTION_CONTRACT,
    REPORT_PATCH_CONTRACT,
    get_system_instruction,
    load_skill,
)


def language_policy(native: str | None, target: str | None, *, onboarding: bool = False) -> str:
    if onboarding and not (native and target):
        return (
            "---\nLanguage policy: start in English. Ask the native language, then the "
            "learning language, one question per turn. Then switch to the learning "
            "language. Accept answers in any language."
        )
    return (
        f"---\nLanguage policy: native {native or '(not set)'}, target {target or 'en'}. "
        f"Write all learner-facing text in {target or 'en'}. Use the native language only "
        "to anticipate interference. JSON keys stay English."
    )


def onboarding_system_instruction(native: str | None, target: str | None) -> str:
    return "\n\n".join(
        [
            get_system_instruction("onboarding"),
            ONBOARDING_EXTRACTION_CONTRACT,
            language_policy(native, target, onboarding=True),
        ]
    )


def lesson_system_instruction(native: str | None, target: str | None, include_vocab: bool) -> str:
    return "\n\n".join(
        [
            get_system_instruction("lesson", include_vocab_formats=include_vocab),
            LESSON_EXTRACTION_CONTRACT,
            language_policy(native, target),
        ]
    )


def lesson_generation_system_instruction(native: str | None, target: str | None) -> str:
    return "\n\n".join(
        [get_system_instruction("lesson"), LESSON_GENERATION_CONTRACT, language_policy(native, target)]
    )


def report_system_instruction(native: str | None, target: str | None) -> str:
    return "\n\n".join([load_skill("report_writer"), REPORT_PATCH_CONTRACT, language_policy(native, target)])


def lesson_context_block(curriculum: dict, profile, due_mistakes) -> str:
    native = profile.native_language if profile else None
    target = (profile.target_language if profile else None) or "en"
    mistakes = "\n".join(f"  - {m.pattern_type}: {m.example_text}" for m in due_mistakes) or "  (none due)"
    return (
        f"Current lesson curriculum (JSON):\n{json.dumps(curriculum or {}, ensure_ascii=False)}\n\n"
        f"Learner: native {native or '(not set)'}, target {target}, "
        f"goal {(profile.goal_outcome if profile else None) or '(not set)'}, "
        f"level {(profile.target_level if profile else None) or '(not set)'}.\n"
        f"Conduct this lesson only in {target}.\n"
        f"Weak patterns due for review:\n{mistakes}"
    )


def generation_user_prompt(context: dict) -> str:
    return (
        "Generate the next lesson's curriculum for this learner. Context (JSON):\n"
        f"{json.dumps(context, default=str, ensure_ascii=False)}\n\n"
        "Pick one grammar focus and one vocab theme aligned to the current milestone; "
        "interleave due mistakes and prior lessons before new material. "
        "Reading and writing only: no speaking slots, no URLs."
    )
