"""Prompt assembly (pure functions)."""

from __future__ import annotations

from types import SimpleNamespace

from app.services.prompt_assembly import lesson_context_block, lesson_system_instruction

PROFILE = SimpleNamespace(native_language="ru", target_language="de", goal_outcome="Emails", target_level="B1")


def test_context_block_lists_due_mistakes_and_sets_the_language() -> None:
    due = SimpleNamespace(pattern_type="articles", example_text="Ich habe Hund")
    block = lesson_context_block({"grammar_focus": "Perfekt"}, PROFILE, [due])
    assert "Conduct this lesson only in de." in block
    assert "articles: Ich habe Hund" in block


def test_lesson_system_instruction_ends_with_the_language_policy() -> None:
    assert lesson_system_instruction("ru", "de", False).rstrip().endswith("JSON keys stay English.")
