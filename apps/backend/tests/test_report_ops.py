from app.models.enums import UserReportType
from app.schemas.report import ReportOp
from app.services.report_ops import apply_report_ops, wrap_section


def test_append_entry_and_patch_section() -> None:
    body = "\n\n".join(
        [
            "# Progress",
            wrap_section("latest_session", "old findings"),
            "## Log",
            wrap_section("update_log", ""),
        ]
    )
    patched = apply_report_ops(
        body,
        [
            ReportOp(
                report_type=UserReportType.progress,
                op="patch_section",
                section_id="latest_session",
                markdown="**This session:** strong articles work.",
            ),
            ReportOp(
                report_type=UserReportType.progress,
                op="append_entry",
                section_id="update_log",
                markdown="## 2026-08-23\nPracticed past simple.",
            ),
        ],
    )
    assert "old findings" not in patched
    assert "strong articles work" in patched
    assert "## 2026-08-23" in patched
    assert patched.index("<!-- section:update_log -->") < patched.index("2026-08-23")
    assert patched.index("2026-08-23") < patched.index("<!-- /section:update_log -->")


def test_unknown_section_is_ignored() -> None:
    body = wrap_section("keep", "hello")
    patched = apply_report_ops(
        body,
        [
            ReportOp(
                report_type=UserReportType.progress,
                op="patch_section",
                section_id="missing",
                markdown="nope",
            )
        ],
    )
    assert patched == body
