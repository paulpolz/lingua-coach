"""Smoke tests for monitoring / telemetry endpoints."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_metrics_endpoint_exposed() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/metrics")
    assert response.status_code == 200
    body = response.text
    assert "http_requests_total" in body or "http_request" in body


@pytest.mark.asyncio
async def test_client_error_telemetry_logs_and_returns_204() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/telemetry/client-errors",
            json={
                "code": "TEST_ERROR",
                "message": "unit test client error",
                "surface": "dashboard",
                "request_id": "req-test-123",
                "path": "/dashboard",
            },
            headers={"X-Request-ID": "req-test-123"},
        )
    assert response.status_code == 204
    assert response.headers.get("X-Request-ID") == "req-test-123"


@pytest.mark.asyncio
async def test_client_error_telemetry_validates_payload() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/telemetry/client-errors",
            json={"code": "", "message": "x"},
        )
    assert response.status_code == 422
