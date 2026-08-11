"""Prometheus custom metrics for LLM usage and client error reporting."""

from __future__ import annotations

from prometheus_client import Counter, Histogram

llm_requests_total = Counter(
    "llm_requests_total",
    "Total Gemini LLM requests",
    ["call_type", "model", "status"],
)

llm_tokens_total = Counter(
    "llm_tokens_total",
    "Total Gemini tokens consumed",
    ["call_type", "model", "direction"],
)

llm_request_duration_seconds = Histogram(
    "llm_request_duration_seconds",
    "Gemini LLM request latency in seconds",
    ["call_type", "model"],
    buckets=(0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0),
)

llm_retries_total = Counter(
    "llm_retries_total",
    "LLM-related retries (e.g. lesson schema repair)",
    ["call_type", "reason"],
)

client_errors_total = Counter(
    "client_errors_total",
    "Client-reported frontend errors",
    ["code", "surface"],
)


def record_llm_call(
    *,
    call_type: str,
    model: str,
    status: str,
    duration_seconds: float,
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> None:
    llm_requests_total.labels(call_type=call_type, model=model, status=status).inc()
    llm_request_duration_seconds.labels(call_type=call_type, model=model).observe(duration_seconds)
    if input_tokens:
        llm_tokens_total.labels(call_type=call_type, model=model, direction="input").inc(input_tokens)
    if output_tokens:
        llm_tokens_total.labels(call_type=call_type, model=model, direction="output").inc(output_tokens)


def record_llm_retry(*, call_type: str, reason: str) -> None:
    llm_retries_total.labels(call_type=call_type, reason=reason).inc()


def record_client_error(*, code: str, surface: str) -> None:
    client_errors_total.labels(code=code or "UNKNOWN", surface=surface or "unknown").inc()
