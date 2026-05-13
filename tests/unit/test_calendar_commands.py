# pyright: basic

from __future__ import annotations

import json
from unittest.mock import patch

from gdocs.__main__ import DEFAULT_SECRETS_DIR, main


def test_calendar_create_event_outputs_json(capsys):
    with patch("gdocs.__main__.CalendarClient") as calendar_cls:
        calendar = calendar_cls.return_value
        calendar.create_event.return_value = {"id": "event-1", "summary": "Planning"}

        code = main([
            "calendar",
            "create-event",
            "--summary",
            "Planning",
            "--start",
            "2026-05-20T10:00:00-07:00",
            "--end",
            "2026-05-20T10:30:00-07:00",
            "--attendee",
            "a@example.com",
            "--attendee",
            "b@example.com",
            "--description",
            "Agenda",
            "--location",
            "Room 1",
            "--timezone",
            "America/Los_Angeles",
        ])

    assert code == 0
    calendar_cls.assert_called_once_with(secrets_dir=DEFAULT_SECRETS_DIR)
    calendar.create_event.assert_called_once_with(
        summary="Planning",
        start="2026-05-20T10:00:00-07:00",
        end="2026-05-20T10:30:00-07:00",
        calendar_id="primary",
        attendees=["a@example.com", "b@example.com"],
        description="Agenda",
        location="Room 1",
        timezone="America/Los_Angeles",
    )
    assert json.loads(capsys.readouterr().out) == {"id": "event-1", "summary": "Planning"}


def test_calendar_list_events_passes_window(capsys):
    with patch("gdocs.__main__.CalendarClient") as calendar_cls:
        calendar = calendar_cls.return_value
        calendar.list_events.return_value = {"items": []}

        code = main([
            "calendar",
            "list-events",
            "--calendar-id",
            "team@example.com",
            "--time-min",
            "2026-05-20T00:00:00-07:00",
            "--time-max",
            "2026-05-21T00:00:00-07:00",
            "--max-results",
            "5",
        ])

    assert code == 0
    calendar.list_events.assert_called_once_with(
        calendar_id="team@example.com",
        time_min="2026-05-20T00:00:00-07:00",
        time_max="2026-05-21T00:00:00-07:00",
        max_results=5,
    )
    assert json.loads(capsys.readouterr().out) == {"items": []}


def test_calendar_error_outputs_json_to_stderr(capsys):
    with patch("gdocs.__main__.CalendarClient") as calendar_cls:
        calendar = calendar_cls.return_value
        calendar.list_events.side_effect = RuntimeError("calendar failed")

        code = main([
            "calendar",
            "list-events",
            "--time-min",
            "2026-05-20T00:00:00-07:00",
        ])

    assert code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {"error": "calendar failed", "type": "RuntimeError"}


def test_calendar_update_event_passes_summary(capsys):
    with patch("gdocs.__main__.CalendarClient") as calendar_cls:
        calendar = calendar_cls.return_value
        calendar.update_event.return_value = {"id": "event-1", "summary": "Renamed"}

        code = main([
            "calendar",
            "update-event",
            "event-1",
            "--summary",
            "Renamed",
        ])

    assert code == 0
    calendar.update_event.assert_called_once_with(
        event_id="event-1",
        calendar_id="primary",
        summary="Renamed",
    )
    assert json.loads(capsys.readouterr().out)["summary"] == "Renamed"


def test_calendar_delete_event_passes_event_id(capsys):
    with patch("gdocs.__main__.CalendarClient") as calendar_cls:
        calendar = calendar_cls.return_value
        calendar.delete_event.return_value = {"deleted": True, "event_id": "event-1", "calendar_id": "primary"}

        code = main(["calendar", "delete-event", "event-1"])

    assert code == 0
    calendar.delete_event.assert_called_once_with(event_id="event-1", calendar_id="primary")
    assert json.loads(capsys.readouterr().out)["deleted"] is True
