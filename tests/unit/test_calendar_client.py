# pyright: basic

from __future__ import annotations

from unittest.mock import patch

from gdocs.calendar_client import CalendarClient


def _client(tmp_path):
    with patch("gdocs.calendar_client.get_credentials", return_value=object()), patch(
        "gdocs.calendar_client.build"
    ) as build:
        client = CalendarClient(tmp_path)
    return client, build, client.calendar.events.return_value


def test_builds_calendar_service(tmp_path):
    _, build, _ = _client(tmp_path)

    build.assert_called_once_with("calendar", "v3", credentials=build.call_args.kwargs["credentials"])


def test_create_event_sends_invites(tmp_path):
    client, _, events = _client(tmp_path)
    events.insert.return_value.execute.return_value = {"id": "event-1", "summary": "Planning"}

    result = client.create_event(
        calendar_id="primary",
        summary="Planning",
        start="2026-05-20T10:00:00-07:00",
        end="2026-05-20T10:30:00-07:00",
        attendees=["a@example.com", "b@example.com"],
        description="Agenda",
        location="Room 1",
        timezone="America/Los_Angeles",
    )

    events.insert.assert_called_once_with(
        calendarId="primary",
        body={
            "summary": "Planning",
            "start": {"dateTime": "2026-05-20T10:00:00-07:00", "timeZone": "America/Los_Angeles"},
            "end": {"dateTime": "2026-05-20T10:30:00-07:00", "timeZone": "America/Los_Angeles"},
            "description": "Agenda",
            "location": "Room 1",
            "attendees": [{"email": "a@example.com"}, {"email": "b@example.com"}],
        },
        sendUpdates="all",
    )
    assert result["id"] == "event-1"


def test_list_events_orders_single_events(tmp_path):
    client, _, events = _client(tmp_path)
    events.list.return_value.execute.return_value = {"items": []}

    result = client.list_events(
        calendar_id="primary",
        time_min="2026-05-20T00:00:00-07:00",
        time_max="2026-05-21T00:00:00-07:00",
        max_results=5,
    )

    events.list.assert_called_once_with(
        calendarId="primary",
        timeMin="2026-05-20T00:00:00-07:00",
        timeMax="2026-05-21T00:00:00-07:00",
        maxResults=5,
        singleEvents=True,
        orderBy="startTime",
    )
    assert result == {"items": []}


def test_update_event_patches_summary(tmp_path):
    client, _, events = _client(tmp_path)
    events.patch.return_value.execute.return_value = {"id": "event-1", "summary": "Renamed"}

    result = client.update_event(event_id="event-1", calendar_id="primary", summary="Renamed")

    events.patch.assert_called_once_with(
        calendarId="primary",
        eventId="event-1",
        body={"summary": "Renamed"},
        sendUpdates="all",
    )
    assert result["summary"] == "Renamed"


def test_delete_event_deletes_with_updates(tmp_path):
    client, _, events = _client(tmp_path)
    events.delete.return_value.execute.return_value = ""

    result = client.delete_event(event_id="event-1", calendar_id="primary")

    events.delete.assert_called_once_with(
        calendarId="primary",
        eventId="event-1",
        sendUpdates="all",
    )
    assert result == {"deleted": True, "event_id": "event-1", "calendar_id": "primary"}
