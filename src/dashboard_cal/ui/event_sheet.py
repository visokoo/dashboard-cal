"""Bottom sheet that shows day-summary or per-event details.

In Flet 0.85 ``BottomSheet`` is a DialogControl: it must NOT live in
``page.controls``, and it is shown via ``page.show_dialog(sheet)`` and
dismissed via ``page.pop_dialog()``.
"""

from __future__ import annotations

from datetime import date, datetime

import flet as ft

from .. import theme
from ..services.calendar import Attendee, Event
from ._util import safe_update


# ----------------------------------------------------------------------
# Formatting helpers (all Windows-safe -- no POSIX ``%-I``/``%-d``)
# ----------------------------------------------------------------------


def _fmt_clock(dt: datetime) -> str:
    """Format e.g. '7:30 AM' without a leading zero on the hour."""
    return dt.strftime("%I:%M %p").lstrip("0")


def _fmt_time(ev: Event) -> str:
    if ev.all_day:
        return "All day"
    return f"{_fmt_clock(ev.start)} \u2013 {_fmt_clock(ev.end)}"


def _fmt_header_date(d: date) -> str:
    # ``%-d`` is POSIX-only; build it from the int instead.
    return f"{d.strftime('%A, %B')} {d.day}"


def _response_label(status: str) -> str:
    return {
        "accepted": "Going",
        "declined": "Declined",
        "tentative": "Maybe",
        "needsAction": "No response",
    }.get(status, status.title() if status else "")


def _response_color(status: str) -> str:
    return {
        "accepted": theme.PRIMARY,
        "declined": ft.Colors.with_opacity(0.65, ft.Colors.RED_300),
        "tentative": theme.ACCENT,
    }.get(status, theme.TEXT_DIM)


# ----------------------------------------------------------------------
# Sheet
# ----------------------------------------------------------------------


class EventSheet(ft.BottomSheet):
    """A single sheet instance that can render two different "screens":

    * Day summary: list of large event cards for a tapped day. Each card is
      clickable to drill in.
    * Event detail: a focused view for one event with location, description,
      attendees, and (when present) a Google Meet link.
    """

    def __init__(self) -> None:
        self._content = ft.Column(
            controls=[],
            spacing=12,
            scroll=ft.ScrollMode.AUTO,
            tight=True,
        )
        super().__init__(
            content=ft.Container(
                content=self._content,
                padding=24,
                bgcolor=theme.SURFACE_HIGH,
                border_radius=ft.BorderRadius.only(top_left=24, top_right=24),
            ),
            scrollable=True,
        )
        # State needed by the in-sheet "Back to ⟨day⟩" affordance when the
        # user drills into a single event and then returns to the summary.
        self._current_day: date | None = None
        self._current_day_events: list[Event] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def show(self, page: ft.Page, day: date, events: list[Event]) -> None:
        """Render the day-summary screen."""
        self._current_day = day
        self._current_day_events = list(events)
        self._render_day(day, events)
        page.show_dialog(self)

    def show_event(self, page: ft.Page, ev: Event) -> None:
        """Render the focused event-detail screen.

        Called either from the calendar grid (no preceding day-summary) or
        from within the day-summary card (with a "back" affordance).
        """
        self._render_event(ev)
        page.show_dialog(self)

    # ------------------------------------------------------------------
    # Renderers
    # ------------------------------------------------------------------
    def _render_day(self, day: date, events: list[Event]) -> None:
        rows: list[ft.Control] = [
            ft.Text(
                _fmt_header_date(day),
                color=theme.TEXT,
                size=24,
                weight=ft.FontWeight.W_600,
            ),
            ft.Divider(color=theme.DIVIDER, height=16),
        ]
        if not events:
            rows.append(ft.Text("No events", color=theme.TEXT_MUTED, size=18))
        else:
            for ev in events:
                rows.append(self._day_card(ev))
        self._content.controls = rows
        # When the sheet is already open (e.g. user tapped "Back" from event
        # detail) we need to push the new controls. ``safe_update`` no-ops
        # when the inner column isn't mounted yet, so the initial ``show``
        # path is unaffected -- the sheet renders cleanly via show_dialog.
        safe_update(self._content)

    def _render_event(self, ev: Event) -> None:
        rows: list[ft.Control] = []

        # Back to day summary (only when we got here from the day view).
        if self._current_day is not None:
            rows.append(self._back_button(self._current_day))

        # Big colour-strip header.
        rows.append(
            ft.Row(
                spacing=12,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Container(
                        width=6,
                        height=48,
                        bgcolor=theme.PRIMARY,
                        border_radius=3,
                    ),
                    ft.Column(
                        expand=True,
                        spacing=2,
                        controls=[
                            ft.Text(
                                _fmt_header_date(ev.start.date()),
                                color=theme.TEXT_MUTED,
                                size=16,
                                weight=ft.FontWeight.W_500,
                            ),
                            ft.Text(
                                ev.title,
                                color=theme.TEXT,
                                size=28,
                                weight=ft.FontWeight.W_600,
                                selectable=True,
                            ),
                            ft.Text(
                                _fmt_time(ev),
                                color=theme.TEXT_MUTED,
                                size=17,
                            ),
                        ],
                    ),
                ],
            )
        )
        rows.append(ft.Divider(color=theme.DIVIDER, height=16))

        if ev.location:
            rows.append(
                _detail_row(
                    icon=ft.Icons.PLACE,
                    primary=ev.location,
                    secondary=None,
                )
            )
        if ev.hangout_link:
            rows.append(
                _detail_row(
                    icon=ft.Icons.VIDEOCAM,
                    primary="Google Meet",
                    secondary=ev.hangout_link,
                )
            )
        if ev.organizer:
            rows.append(
                _detail_row(
                    icon=ft.Icons.PERSON,
                    primary=f"Organizer: {ev.organizer}",
                    secondary=None,
                )
            )

        if ev.attendees:
            rows.append(
                ft.Row(
                    spacing=12,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                    controls=[
                        ft.Icon(
                            icon=ft.Icons.GROUP,
                            color=theme.TEXT_MUTED,
                            size=20,
                        ),
                        ft.Column(
                            expand=True,
                            spacing=4,
                            controls=[
                                ft.Text(
                                    f"{len(ev.attendees)} guests",
                                    color=theme.TEXT,
                                    size=17,
                                    weight=ft.FontWeight.W_500,
                                ),
                                *[_attendee_row(a) for a in ev.attendees],
                            ],
                        ),
                    ],
                )
            )

        if ev.description:
            rows.append(ft.Divider(color=theme.DIVIDER, height=16))
            rows.append(
                ft.Text(
                    ev.description,
                    color=theme.TEXT,
                    size=16,
                    selectable=True,
                )
            )

        if not (ev.location or ev.description or ev.attendees or ev.organizer):
            rows.append(
                ft.Text("No additional details", color=theme.TEXT_DIM, size=16)
            )

        self._content.controls = rows
        # ``_render_event`` runs both as the initial render (before the sheet
        # is shown) and as a follow-up from a day-card tap (after the sheet
        # is already open). ``safe_update`` flushes in the second case and
        # no-ops in the first -- avoiding "Control must be added to the page
        # first" on initial open.
        safe_update(self._content)

    # ------------------------------------------------------------------
    # Day-card + back button helpers
    # ------------------------------------------------------------------
    def _day_card(self, ev: Event) -> ft.Control:
        """A large, clickable card for the day-summary list."""
        title = ft.Text(
            ev.title,
            color=theme.TEXT,
            size=20,
            weight=ft.FontWeight.W_600,
            max_lines=2,
            overflow=ft.TextOverflow.ELLIPSIS,
        )
        subtitle = ft.Text(
            _fmt_time(ev),
            color=theme.TEXT_MUTED,
            size=16,
        )
        meta_bits: list[ft.Control] = []
        if ev.location:
            meta_bits.append(
                _inline_meta(ft.Icons.PLACE, ev.location)
            )
        if ev.attendees:
            meta_bits.append(
                _inline_meta(
                    ft.Icons.GROUP,
                    f"{len(ev.attendees)} guests",
                )
            )
        if ev.hangout_link:
            meta_bits.append(_inline_meta(ft.Icons.VIDEOCAM, "Google Meet"))

        body_children: list[ft.Control] = [title, subtitle]
        if meta_bits:
            body_children.append(
                ft.Row(spacing=14, wrap=True, controls=meta_bits)
            )

        def _on_tap(_e: ft.ControlEvent, event: Event = ev) -> None:
            self._render_event(event)

        return ft.Container(
            content=ft.Row(
                spacing=12,
                vertical_alignment=ft.CrossAxisAlignment.START,
                controls=[
                    ft.Container(
                        width=6,
                        bgcolor=theme.PRIMARY,
                        border_radius=3,
                    ),
                    ft.Column(
                        expand=True,
                        spacing=4,
                        controls=body_children,
                    ),
                    ft.Icon(
                        icon=ft.Icons.CHEVRON_RIGHT,
                        color=theme.TEXT_MUTED,
                        size=24,
                    ),
                ],
            ),
            padding=ft.Padding.symmetric(horizontal=16, vertical=14),
            bgcolor=theme.SURFACE_LOW,
            border_radius=theme.CARD_RADIUS,
            on_click=_on_tap,
            ink=True,
        )

    def _back_button(self, day: date) -> ft.Control:
        def _on_back(
            _e: ft.ControlEvent,
            d: date = day,
            evs: list[Event] = self._current_day_events,
        ) -> None:
            self._render_day(d, evs)

        return ft.Container(
            content=ft.Row(
                spacing=4,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Icon(
                        icon=ft.Icons.ARROW_BACK,
                        color=theme.TEXT_MUTED,
                        size=20,
                    ),
                    ft.Text(
                        f"Back to {_fmt_header_date(day)}",
                        color=theme.TEXT_MUTED,
                        size=15,
                        weight=ft.FontWeight.W_500,
                    ),
                ],
            ),
            padding=ft.Padding.symmetric(horizontal=8, vertical=4),
            border_radius=8,
            on_click=_on_back,
            ink=True,
        )


# ----------------------------------------------------------------------
# Small reusable bits at module level (no closure capture, easier to test)
# ----------------------------------------------------------------------


def _inline_meta(icon: str, text: str) -> ft.Control:
    return ft.Row(
        spacing=4,
        tight=True,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
        controls=[
            ft.Icon(icon=icon, color=theme.TEXT_MUTED, size=16),
            ft.Text(
                text,
                color=theme.TEXT_MUTED,
                size=15,
                max_lines=1,
                overflow=ft.TextOverflow.ELLIPSIS,
            ),
        ],
    )


def _detail_row(*, icon: str, primary: str, secondary: str | None) -> ft.Control:
    body: list[ft.Control] = [
        ft.Text(primary, color=theme.TEXT, size=17, selectable=True),
    ]
    if secondary:
        body.append(
            ft.Text(secondary, color=theme.TEXT_MUTED, size=15, selectable=True)
        )
    return ft.Row(
        spacing=12,
        vertical_alignment=ft.CrossAxisAlignment.START,
        controls=[
            ft.Icon(icon=icon, color=theme.TEXT_MUTED, size=22),
            ft.Column(expand=True, spacing=2, controls=body),
        ],
    )


def _attendee_row(a: Attendee) -> ft.Control:
    label = a.display_name + (" (you)" if a.self else "")
    return ft.Row(
        spacing=8,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
        controls=[
            ft.Container(
                width=8,
                height=8,
                border_radius=4,
                bgcolor=_response_color(a.response_status),
            ),
            ft.Text(label, color=theme.TEXT, size=16, expand=True),
            ft.Text(
                _response_label(a.response_status),
                color=theme.TEXT_DIM,
                size=14,
            ),
        ],
    )
