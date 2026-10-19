"""Eval scoring and the upload flag. No Gemini and no LangSmith account."""

from evals.run import main, score_case


def test_expect_fail_passes_when_check_fails() -> None:
    row = score_case(
        case={
            "mode": "lesson",
            "expect_fail": True,
            "checks": {"deterministic": ["extract_lesson_turn"]},
        },
        fixture={},
        completion="plain prose with no fence",
        harness_error=None,
        suite="regression",
    )
    assert row["checks"] == 1
    assert row["gate"] == 1


def test_expect_fail_does_not_invert_a_harness_error() -> None:
    row = score_case(
        case={"mode": "lesson", "expect_fail": True, "checks": {"deterministic": []}},
        fixture={},
        completion="",
        harness_error="replay fixture missing",
        suite="calibration",
    )
    assert row["checks"] == 0
    assert row["gate"] == 0


def test_calibration_check_failure_is_not_a_gate() -> None:
    row = score_case(
        case={
            "mode": "lesson",
            "checks": {"deterministic": ["extract_lesson_turn"]},
        },
        fixture={},
        completion="no fence",
        harness_error=None,
        suite="calibration",
    )
    assert row["checks"] == 0
    assert row["gate"] == 1


def test_upload_requires_api_key(monkeypatch) -> None:
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    assert main(["--upload", "--replay", "--suite", "regression"]) == 1


def test_upload_refuses_inbox_stubs(monkeypatch) -> None:
    monkeypatch.setenv("LANGSMITH_API_KEY", "test-key")
    assert main(["--upload", "--replay", "--suite", "inbox"]) == 1
