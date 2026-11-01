"""Active-minute measurement and the target lookup (pure functions)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.services.lesson_timing import TimeBudgetRequired, active_minutes_between, lesson_target_minutes, target_minutes

T0 = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)


def _at(*minutes: float) -> list[datetime]:
    return [T0 + timedelta(minutes=m) for m in minutes]


def test_gaps_longer_than_the_idle_cap_count_as_the_cap() -> None:
    # Messages 1, 3 and 40 minutes apart: 1 + 3 + 5 (capped).
    assert active_minutes_between(_at(0, 1, 4, 44), idle_cap_minutes=5) == 9


@pytest.mark.parametrize("times", [[], _at(0)])
def test_fewer_than_two_messages_is_zero(times: list[datetime]) -> None:
    assert active_minutes_between(times, idle_cap_minutes=5) == 0


def test_order_does_not_matter() -> None:
    assert active_minutes_between(_at(8, 0, 4), idle_cap_minutes=5) == 8


def test_target_minutes_reads_the_profile() -> None:
    assert target_minutes(SimpleNamespace(time_budget={"minutes_per_session": 20})) == 20  # type: ignore[arg-type]


@pytest.mark.parametrize("budget", [None, {}, {"minutes_per_session": None}, {"minutes_per_session": 0}])
def test_target_minutes_has_no_default(budget: dict | None) -> None:
    with pytest.raises(TimeBudgetRequired):
        target_minutes(SimpleNamespace(time_budget=budget))  # type: ignore[arg-type]
    with pytest.raises(TimeBudgetRequired):
        target_minutes(None)


def test_lesson_target_prefers_the_payload_over_a_changed_profile() -> None:
    lesson = SimpleNamespace(payload={"target_minutes": 15})
    profile = SimpleNamespace(time_budget={"minutes_per_session": 30})
    assert lesson_target_minutes(lesson, profile) == 15  # type: ignore[arg-type]
    legacy = SimpleNamespace(payload={"curriculum": {"slots": []}})
    assert lesson_target_minutes(legacy, profile) == 30  # type: ignore[arg-type]
    assert lesson_target_minutes(legacy, None) is None  # type: ignore[arg-type]
