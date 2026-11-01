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
