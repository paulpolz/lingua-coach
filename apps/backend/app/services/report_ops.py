"""Incremental markdown patches inside `<!-- section:ID -->` markers."""

from __future__ import annotations

import re


def wrap_section(section_id: str, inner: str) -> str:
    inner = inner.strip("\n")
    body = f"\n{inner}\n" if inner else "\n"
    return f"<!-- section:{section_id} -->{body}<!-- /section:{section_id} -->"


def apply_report_op(body: str, op: dict) -> str:
    section_id = op.get("section_id", "")
    open_m, close_m = f"<!-- section:{section_id} -->", f"<!-- /section:{section_id} -->"
    pattern = re.compile(re.escape(open_m) + r"(.*?)" + re.escape(close_m), re.DOTALL)
    match = pattern.search(body)
    if match is None:
        return body
    snippet = str(op.get("markdown", "")).strip("\n")
    existing = match.group(1).strip("\n")
    if op.get("op") == "append_entry" and existing:
        snippet = f"{existing}\n\n{snippet}"
    replacement = f"{open_m}\n{snippet}\n{close_m}" if snippet else f"{open_m}\n{close_m}"
    return body[: match.start()] + replacement + body[match.end() :]
