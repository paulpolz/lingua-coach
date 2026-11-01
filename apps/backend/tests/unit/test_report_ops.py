"""Report section ops, log tails and the log-section guard."""

from __future__ import annotations

from app.services.report_ops import apply_report_op, wrap_section
from app.services.report_seed import blank_progress_markdown


def _progress_with_entries(n: int, size: int = 20) -> str:
    entries = "\n\n".join(f"- 2026-10-{i:02d}: entry {i} " + "x" * size for i in range(1, n + 1))
    return blank_progress_markdown().replace(wrap_section("update_log", ""), wrap_section("update_log", entries))


def test_append_entry_adds_after_existing_entries() -> None:
    body = apply_report_op(
        blank_progress_markdown(), {"op": "append_entry", "section_id": "update_log", "markdown": "a"}
    )
    body = apply_report_op(body, {"op": "append_entry", "section_id": "update_log", "markdown": "b"})
    assert "<!-- section:update_log -->\na\n\nb\n<!-- /section:update_log -->" in body


def test_patch_section_replaces_and_unknown_section_is_a_no_op() -> None:
    body = blank_progress_markdown()
    patched = apply_report_op(body, {"op": "patch_section", "section_id": "latest_session", "markdown": "new"})
    assert "<!-- section:latest_session -->\nnew\n" in patched
    assert apply_report_op(body, {"op": "patch_section", "section_id": "nope", "markdown": "x"}) == body
