from __future__ import annotations

"""Google Calendar API client: direct SDK wrapper."""

from pathlib import Path
from typing import Any

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from .auth import get_credentials
from .client import _http_error_message, _retry_transient


class CalendarClient:
    """Single entry point for Google Calendar operations."""

    def __init__(self, secrets_dir: Path):
        creds = get_credentials(secrets_dir)
        self.calendar: Any = build("calendar", "v3", credentials=creds)

    def create_event(
        self,
        *,
        summary: str,
        start: str,
        end: str,
        calendar_id: str = "primary",
        attendees: list[str] | None = None,
        description: str | None = None,
        location: str | None = None,
        timezone: str | None = None,
    ) -> dict[str, object]:
        body: dict[str, object] = {
            "summary": summary,
            "start": _time_spec(start, timezone),
            "end": _time_spec(end, timezone),
        }
        if description:
            body["description"] = description
        if location:
            body["location"] = location
        if attendees:
            body["attendees"] = [{"email": email} for email in attendees]
        try:
            return _retry_transient(
                lambda: self.calendar.events().insert(
                    calendarId=calendar_id,
                    body=body,
                    sendUpdates="all",
                ).execute()
            )
        except HttpError as exc:
            raise RuntimeError(_http_error_message("Failed to create Calendar event", exc)) from exc

    def update_event(
        self,
        *,
        event_id: str,
        calendar_id: str = "primary",
        summary: str | None = None,
    ) -> dict[str, object]:
        body: dict[str, object] = {}
        if summary is not None:
            body["summary"] = summary
        if not body:
            raise ValueError("At least one event field must be provided")
        try:
            return _retry_transient(
                lambda: self.calendar.events().patch(
                    calendarId=calendar_id,
                    eventId=event_id,
                    body=body,
                    sendUpdates="all",
                ).execute()
            )
        except HttpError as exc:
            raise RuntimeError(_http_error_message(f"Failed to update Calendar event '{event_id}'", exc)) from exc

    def delete_event(
        self,
        *,
        event_id: str,
        calendar_id: str = "primary",
    ) -> dict[str, object]:
        try:
            _ = _retry_transient(
                lambda: self.calendar.events().delete(
                    calendarId=calendar_id,
                    eventId=event_id,
                    sendUpdates="all",
                ).execute()
            )
            return {"deleted": True, "event_id": event_id, "calendar_id": calendar_id}
        except HttpError as exc:
            raise RuntimeError(_http_error_message(f"Failed to delete Calendar event '{event_id}'", exc)) from exc

    def list_events(
        self,
        *,
        time_min: str,
        calendar_id: str = "primary",
        time_max: str | None = None,
        max_results: int = 10,
    ) -> dict[str, object]:
        kwargs: dict[str, object] = {
            "calendarId": calendar_id,
            "timeMin": time_min,
            "maxResults": max_results,
            "singleEvents": True,
            "orderBy": "startTime",
        }
        if time_max:
            kwargs["timeMax"] = time_max
        try:
            return _retry_transient(lambda: self.calendar.events().list(**kwargs).execute())
        except HttpError as exc:
            raise RuntimeError(_http_error_message("Failed to list Calendar events", exc)) from exc


def _time_spec(value: str, timezone: str | None) -> dict[str, str]:
    spec = {"dateTime": value}
    if timezone:
        spec["timeZone"] = timezone
    return spec
