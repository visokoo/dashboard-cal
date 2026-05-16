"""Google Calendar adapter (read-only).

Fetches events in a date window and normalizes them into ``Event`` dataclasses
the UI can render without depending on Google's API shape.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from typing import Iterable

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

log = logging.getLogger(__name__)


def _local_tz() -> tzinfo:
    """Return the system's local tzinfo.

    We pull this from ``datetime.now().astimezone()`` so it tracks DST and the
    OS-configured timezone without an explicit pytz/zoneinfo dependency.
    """
    local = datetime.now().astimezone().tzinfo
    # astimezone() on a naive datetime always populates tzinfo; fall back to
    # UTC defensively so this function can never return ``None``.
    return local if local is not None else timezone.utc


@dataclass(frozen=True)
class Attendee:
    """A normalized attendee record.

    ``email`` is the only field that's always present (Google returns it as
    the primary key). ``display_name`` falls back to the local part of the
    email. ``response_status`` is one of ``accepted``, ``declined``,
    ``tentative``, ``needsAction`` (Google's vocabulary, preserved verbatim
    for the UI to render appropriately).
    """

    email: str
    display_name: str
    response_status: str
    organizer: bool
    self: bool


@dataclass(frozen=True)
class Event:
    id: str
    calendar_id: str
    title: str
    start: datetime
    end: datetime
    all_day: bool
    location: str | None
    description: str | None
    color_id: str | None
    organizer: str | None = None
    attendees: tuple[Attendee, ...] = ()
    hangout_link: str | None = None


class CalendarService:
    """Thin wrapper around the Calendar v3 events.list endpoint."""

    def __init__(self, creds: Credentials, calendar_ids: Iterable[str]) -> None:
        # cache_discovery=False keeps things light and avoids stale-cache warnings.
        self._svc = build("calendar", "v3", credentials=creds, cache_discovery=False)
        self._calendar_ids = list(calendar_ids)

    async def list_events(self, start: date, end: date) -> list[Event]:
        """Fetch events between ``start`` (inclusive) and ``end`` (exclusive)."""
        time_min = datetime.combine(start, time.min, tzinfo=timezone.utc).isoformat()
        time_max = datetime.combine(end, time.min, tzinfo=timezone.utc).isoformat()
        events: list[Event] = []
        loop = asyncio.get_running_loop()
        for cal_id in self._calendar_ids:
            try:
                raw = await loop.run_in_executor(
                    None, self._fetch_one, cal_id, time_min, time_max
                )
            except HttpError as e:
                # Generic message - don't surface raw Google error details to logs/UI
                # (logging rule: error messages and responses).
                log.warning("calendar: fetch failed status=%s", e.resp.status)
                continue
            events.extend(_parse_events(cal_id, raw))
        events.sort(key=lambda e: e.start)
        log.info(
            "calendar: fetched count=%d window=%s..%s",
            len(events), start.isoformat(), end.isoformat(),
        )
        return events

    def _fetch_one(self, calendar_id: str, time_min: str, time_max: str) -> list[dict]:
        items: list[dict] = []
        page_token: str | None = None
        while True:
            resp = (
                self._svc.events()
                .list(
                    calendarId=calendar_id,
                    timeMin=time_min,
                    timeMax=time_max,
                    singleEvents=True,
                    orderBy="startTime",
                    maxResults=250,
                    pageToken=page_token,
                )
                .execute()
            )
            items.extend(resp.get("items", []))
            page_token = resp.get("nextPageToken")
            if not page_token:
                return items


def _parse_events(calendar_id: str, items: list[dict]) -> list[Event]:
    """Normalize Google Calendar items.

    All returned datetimes are tz-aware (anchored to the local system tz) so
    that timed and all-day events can be compared, sorted, and grouped via
    ``.date()`` without raising ``TypeError: can't compare offset-naive and
    offset-aware datetimes``.
    """
    local = _local_tz()
    out: list[Event] = []
    for it in items:
        start_raw = it.get("start", {})
        end_raw = it.get("end", {})
        if "dateTime" in start_raw:
            # Google returns RFC3339 strings with an offset, so fromisoformat
            # yields tz-aware datetimes. Convert to local tz so .date() is the
            # date the user actually sees on their wall clock.
            start_dt = datetime.fromisoformat(start_raw["dateTime"])
            end_dt = datetime.fromisoformat(end_raw.get("dateTime", start_raw["dateTime"]))
            if start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=local)
            if end_dt.tzinfo is None:
                end_dt = end_dt.replace(tzinfo=local)
            start = start_dt.astimezone(local)
            end = end_dt.astimezone(local)
            all_day = False
        elif "date" in start_raw:
            start_d = date.fromisoformat(start_raw["date"])
            end_d = date.fromisoformat(end_raw.get("date", start_raw["date"]))
            # Anchor at local midnight so this datetime is tz-aware and
            # ``.date()`` returns the same calendar day in local time.
            start = datetime.combine(start_d, time.min, tzinfo=local)
            # Google represents all-day end as the day after; keep that.
            end = datetime.combine(end_d, time.min, tzinfo=local) - timedelta(seconds=1)
            all_day = True
        else:
            continue
        out.append(
            Event(
                id=str(it.get("id", "")),
                calendar_id=calendar_id,
                title=str(it.get("summary", "(no title)")),
                start=start,
                end=end,
                all_day=all_day,
                location=it.get("location"),
                description=it.get("description"),
                color_id=it.get("colorId"),
                organizer=_organizer_display(it.get("organizer")),
                attendees=_parse_attendees(it.get("attendees", [])),
                hangout_link=it.get("hangoutLink"),
            )
        )
    return out


def _organizer_display(org: dict | None) -> str | None:
    if not org:
        return None
    name = org.get("displayName") or org.get("email")
    return str(name) if name else None


def _parse_attendees(raw: list[dict]) -> tuple[Attendee, ...]:
    """Normalize Google's attendee dicts into our tuple of Attendee records.

    We never log or surface the raw list (it can contain external emails);
    only structured display fields are exposed to the UI.
    """
    out: list[Attendee] = []
    for a in raw:
        email = str(a.get("email", "")).strip()
        if not email:
            continue
        display = a.get("displayName") or email.split("@", 1)[0]
        out.append(
            Attendee(
                email=email,
                display_name=str(display),
                response_status=str(a.get("responseStatus", "needsAction")),
                organizer=bool(a.get("organizer", False)),
                self=bool(a.get("self", False)),
            )
        )
    return tuple(out)
