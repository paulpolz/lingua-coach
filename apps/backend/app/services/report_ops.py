"""Apply incremental markdown patches to coach report documents."""

from __future__ import annotations

import logging
import re

from app.schemas.report import ReportOp

logger = logging.getLogger(__name__)

_SECTION_OPEN = "<!-- section:{id} -->"
_SECTION_CLOSE = "<!-- /section:{id} -->"


def section_markers(section_id: str) -> tuple[str, str]:
    return _SECTION_OPEN.format(id=section_id), _SECTION_CLOSE.format(id=section_id)


def wrap_section(section_id: str, inner: str) -> str:
    open_m, close_m = section_markers(section_id)
    inner = inner.strip("\n")
    return f"{open_m}\n{inner}\n{close_m}" if inner else f"{open_m}\n{close_m}"


def apply_report_op(body: str, op: ReportOp) -> str:
    """Apply one op. Unknown sections are left unchanged."""
    open_m, close_m = section_markers(op.section_id)
    pattern = re.compile(
        re.escape(open_m) + r"(.*?)" + re.escape(close_m),
        re.DOTALL,
    )
    match = pattern.search(body)
    if match is None:
        logger.info(
            "report_op_unknown_section",
            extra={"section_id": op.section_id, "report_type": op.report_type.value, "op": op.op},
        )
        return body

    inner = match.group(1)
    snippet = op.markdown.strip("\n")
    if op.op == "patch_section":
        new_inner = f"\n{snippet}\n" if snippet else "\n"
    else:
        existing = inner.strip("\n")
        if existing:
            new_inner = f"\n{existing}\n\n{snippet}\n"
        else:
            new_inner = f"\n{snippet}\n"
    replacement = f"{open_m}{new_inner}{close_m}"
    return pattern.sub(replacement, body, count=1)


def apply_report_ops(body: str, ops: list[ReportOp]) -> str:
    updated = body
    for op in ops:
        updated = apply_report_op(updated, op)
    return updated
