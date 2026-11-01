"""Incremental markdown patches inside `<!-- section:ID -->` markers."""

from __future__ import annotations

import re


def wrap_section(section_id: str, inner: str) -> str:
    inner = inner.strip("\n")
    body = f"\n{inner}\n" if inner else "\n"
    return f"<!-- section:{section_id} -->{body}<!-- /section:{section_id} -->"


# Append-only logs: our code adds entries (append_entry), so the model only needs the tail.
LOG_SECTIONS: dict[str, frozenset[str]] = {
    "progress": frozenset({"update_log"}),
    "errors_log": frozenset({"daily_log"}),
}
LOG_TAIL_ENTRIES = 5
LOG_TAIL_CHARS = 3000


def is_log_section(report_type: str, section_id: str) -> bool:
    return section_id in LOG_SECTIONS.get(report_type, frozenset())


def _section(section_id: str) -> re.Pattern[str]:
    return re.compile(
        re.escape(f"<!-- section:{section_id} -->") + r"(.*?)" + re.escape(f"<!-- /section:{section_id} -->"),
        re.DOTALL,
    )


def trim_log_sections(report_type: str, body: str) -> str:
    """Prompt copy of a report: log sections keep their last entries (blank-line separated),
    at most LOG_TAIL_ENTRIES and LOG_TAIL_CHARS, with a marker saying how many were left out."""
    for section_id in LOG_SECTIONS.get(report_type, ()):
        match = _section(section_id).search(body)
        if match is None:
            continue
        entries = [e for e in match.group(1).strip("\n").split("\n\n") if e.strip()]
        tail = entries[-LOG_TAIL_ENTRIES:]
        while len(tail) > 1 and len("\n\n".join(tail)) > LOG_TAIL_CHARS:
            tail.pop(0)
        text = "\n\n".join(tail)[-LOG_TAIL_CHARS:]
        if len(tail) == len(entries) and text == "\n\n".join(entries):
            continue
        marker = f"(showing the last {len(tail)} of {len(entries)} entries)"
        replacement = f"<!-- section:{section_id} --> {marker}\n{text}\n<!-- /section:{section_id} -->"
        body = body[: match.start()] + replacement + body[match.end() :]
    return body


def apply_report_op(body: str, op: dict) -> str:
    section_id = op.get("section_id", "")
    open_m, close_m = f"<!-- section:{section_id} -->", f"<!-- /section:{section_id} -->"
    match = _section(section_id).search(body)
    if match is None:
        return body
    snippet = str(op.get("markdown", "")).strip("\n")
    existing = match.group(1).strip("\n")
    if op.get("op") == "append_entry" and existing:
        snippet = f"{existing}\n\n{snippet}"
    replacement = f"{open_m}\n{snippet}\n{close_m}" if snippet else f"{open_m}\n{close_m}"
    return body[: match.start()] + replacement + body[match.end() :]
