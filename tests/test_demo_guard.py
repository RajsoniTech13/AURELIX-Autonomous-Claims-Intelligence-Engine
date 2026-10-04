"""
The demo capacity guard's day boundary.

It resets with Gemini's free-tier quota, at midnight America/Los_Angeles. It used a fixed UTC-8
offset, which ignores daylight saving: under PDT its day ended an hour late, so for an hour a day
it disagreed with the quota ledger about the date, and the reset time it showed visitors was
wrong — on 2026-10-04 it reported a reset that had already passed.
"""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from platform_backend.services import demo_guard

LA = ZoneInfo("America/Los_Angeles")


class FrozenDatetime(datetime):
    frozen: datetime

    @classmethod
    def now(cls, tz=None):
        return cls.frozen.astimezone(tz) if tz else cls.frozen


@pytest.mark.parametrize("instant,expected_reset", [
    # PDT (UTC-7): midnight Pacific is 07:00Z. The fixed offset said 08:00Z.
    (datetime(2026, 10, 4, 7, 30, tzinfo=timezone.utc), datetime(2026, 10, 5, 7, 0, tzinfo=timezone.utc)),
    # PST (UTC-8), after the clocks go back: midnight Pacific is 08:00Z.
    (datetime(2026, 12, 1, 12, 0, tzinfo=timezone.utc), datetime(2026, 12, 2, 8, 0, tzinfo=timezone.utc)),
])
def test_the_reset_is_midnight_in_los_angeles_in_every_season(monkeypatch, instant, expected_reset):
    FrozenDatetime.frozen = instant
    monkeypatch.setattr(demo_guard, "datetime", FrozenDatetime)
    assert demo_guard.next_reset() == expected_reset
    assert demo_guard.next_reset() > instant


def test_the_guard_and_the_quota_ledger_agree_on_the_date(monkeypatch):
    from agent_core.services import quota_ledger
    FrozenDatetime.frozen = datetime(2026, 10, 4, 7, 30, tzinfo=timezone.utc)   # 00:30 PDT
    monkeypatch.setattr(demo_guard, "datetime", FrozenDatetime)
    monkeypatch.setattr(quota_ledger, "datetime", FrozenDatetime)
    assert demo_guard._today() == quota_ledger._today() == "2026-10-04"
