"""Report section ops, log tails and the log-section guard."""

from __future__ import annotations

from app.services.report_ops import apply_report_op, is_log_section, trim_log_sections, wrap_section
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


def test_log_tail_sends_the_last_five_entries_with_a_marker() -> None:
    trimmed = trim_log_sections("progress", _progress_with_entries(87))
    assert "(showing the last 5 of 87 entries)" in trimmed
    assert "entry 87" in trimmed and "entry 83" in trimmed
    assert "entry 82 " not in trimmed
    assert "<!-- section:latest_session -->" in trimmed  # snapshot sections untouched


def test_log_tail_is_capped_at_3000_chars() -> None:
    trimmed = trim_log_sections("progress", _progress_with_entries(10, size=1000))
    inner = trimmed.split("<!-- section:update_log -->")[1].split("<!-- /section:update_log -->")[0]
    assert len(inner) <= 3000 + 60
    assert "entry 10" in inner


def test_short_logs_and_other_reports_are_unchanged() -> None:
    body = _progress_with_entries(3)
    assert trim_log_sections("progress", body) == body
    assert trim_log_sections("roadmap", body) == body


def test_log_sections() -> None:
    assert is_log_section("progress", "update_log")
    assert is_log_section("errors_log", "daily_log")
    assert not is_log_section("progress", "latest_session")
