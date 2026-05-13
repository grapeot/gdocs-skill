# pyright: basic

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .calendar_client import CalendarClient


def run_calendar_command(
    data: dict[str, object],
    secrets_dir: Path,
    calendar_client_cls: type[CalendarClient],
) -> object:
    calendar = calendar_client_cls(secrets_dir=secrets_dir)
    command = str(data["calendar_command"])
    if command == "create-event":
        return calendar.create_event(
            summary=str(data["summary"]),
            start=str(data["start"]),
            end=str(data["end"]),
            calendar_id=str(data.get("calendar_id") or "primary"),
            attendees=_list_arg(data.get("attendee")),
            description=_str_optional(data.get("description")),
            location=_str_optional(data.get("location")),
            timezone=_str_optional(data.get("timezone")),
        )
    if command == "update-event":
        return calendar.update_event(
            event_id=str(data["event_id"]),
            calendar_id=str(data.get("calendar_id") or "primary"),
            summary=_str_optional(data.get("summary")),
        )
    if command == "delete-event":
        return calendar.delete_event(
            event_id=str(data["event_id"]),
            calendar_id=str(data.get("calendar_id") or "primary"),
        )
    if command == "list-events":
        return calendar.list_events(
            calendar_id=str(data.get("calendar_id") or "primary"),
            time_min=str(data["time_min"]),
            time_max=_str_optional(data.get("time_max")),
            max_results=_int_arg(data, "max_results"),
        )
    raise RuntimeError("Unknown Calendar command")


def _list_arg(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def _str_optional(value: object | None) -> str | None:
    if value is None:
        return None
    return str(value)


def _int_arg(data: dict[str, object], key: str) -> int:
    value = data[key]
    if isinstance(value, int):
        return value
    return int(str(value))
