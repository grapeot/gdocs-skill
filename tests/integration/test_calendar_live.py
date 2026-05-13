# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from gdocs.calendar_client import CalendarClient


pytestmark = pytest.mark.skipif(
    os.getenv("GDOCS_ENABLE_CALENDAR_LIVE_TESTS") != "1",
    reason="Calendar live integration tests are disabled",
)


SECRETS_DIR = Path(__file__).resolve().parents[2] / "secrets"


@pytest.fixture(scope="module")
def calendar() -> CalendarClient:
    if not (SECRETS_DIR / "credentials.json").exists():
        pytest.skip("secrets/credentials.json is not configured")
    return CalendarClient(secrets_dir=SECRETS_DIR)


@pytest.mark.live_integration
def test_calendar_create_and_list_event(calendar: CalendarClient) -> None:
    calendar_id = os.getenv("GDOCS_LIVE_CALENDAR_ID") or "primary"
    attendee = os.getenv("GDOCS_LIVE_CALENDAR_ATTENDEE")
    start_dt = datetime.now(timezone.utc) + timedelta(days=7)
    end_dt = start_dt + timedelta(minutes=15)
    time_min = (start_dt - timedelta(minutes=5)).isoformat()
    time_max = (end_dt + timedelta(minutes=5)).isoformat()
    summary = f"gdocs-skill-live-test-{int(time.time())}"

    created: dict[str, object] | None = None
    try:
        created = calendar.create_event(
            calendar_id=calendar_id,
            summary=summary,
            start=start_dt.isoformat(),
            end=end_dt.isoformat(),
            attendees=[attendee] if attendee else None,
            description="Created by a gated gdocs-skill Calendar live integration test.",
        )

        event_id = str(created["id"])
        listed = calendar.list_events(
            calendar_id=calendar_id,
            time_min=time_min,
            time_max=time_max,
            max_results=10,
        )
        items = listed.get("items", [])
        assert any(item.get("summary") == summary for item in items if isinstance(item, dict))

        renamed_summary = f"{summary}-renamed"
        updated = calendar.update_event(
            calendar_id=calendar_id,
            event_id=event_id,
            summary=renamed_summary,
        )
        assert updated["summary"] == renamed_summary

        relisted = calendar.list_events(
            calendar_id=calendar_id,
            time_min=time_min,
            time_max=time_max,
            max_results=10,
        )
        relisted_items = relisted.get("items", [])
        assert any(item.get("summary") == renamed_summary for item in relisted_items if isinstance(item, dict))
    finally:
        if created is not None:
            _ = calendar.delete_event(calendar_id=calendar_id, event_id=str(created["id"]))
