"""Gemini error classification — quota vs context limit."""

from google.genai.errors import APIError as GenAIAPIError

from app.services.gemini import _classify_genai_error


def test_resource_exhausted_maps_to_quota() -> None:
    exc = GenAIAPIError(
        429,
        {"error": {"status": "RESOURCE_EXHAUSTED", "message": "Quota exceeded"}},
    )
    assert _classify_genai_error(exc) == ("LLM_QUOTA_EXCEEDED", "quota")


def test_context_limit_is_not_classified_as_quota() -> None:
    exc = GenAIAPIError(
        400,
        {"error": {"status": "INVALID_ARGUMENT", "message": "maximum context length exceeded"}},
    )
    assert _classify_genai_error(exc) == ("LLM_CONTEXT_LIMIT", "context_limit")
