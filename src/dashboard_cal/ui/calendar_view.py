"""Month and week calendar views.

The month view shows a 7xN grid of day cells with event titles inside each
cell. The week view is a Google-Calendar-style scrollable time grid: day
labels and all-day events along the top, then a 24-hour scrollable area with
events positioned at their absolute start time.
"""

from __future__ import annotations

from calendar import Calendar
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from typing import Callable

import flet as ft

from .. import theme
from ..services.calendar import Event
from ._util import safe_update

OnDayTap = Callable[[date], None]
OnEventTap = Callable[[Event], None]


# ----------------------------------------------------------------------
# Formatting helpers (Windows-safe -- no POSIX ``%-I``/``%-d``)
# ----------------------------------------------------------------------


def _fmt_hour_label(hour: int) -> str:
    """``0`` -> "12 AM", ``13`` -> "1 PM"."""
    if hour == 0:
        return "12 AM"
    if hour < 12:
        return f"{hour} AM"
    if hour == 12:
        return "12 PM"
    return f"{hour - 12} PM"


def _short_day_label(d: date) -> tuple[str, str]:
    """('Mon', '12') without POSIX directives."""
    return d.strftime("%a"), str(d.day)


# ----------------------------------------------------------------------
# Week-view event layout: greedy column packing for overlaps
# ----------------------------------------------------------------------


def _pack_overlapping(events: list[Event]) -> list[tuple[Event, int, int]]:
    """Greedy column assignment for visually-overlapping events.

    Returns a list of ``(event, column_index, total_columns)`` triples. Each
    event is placed in the leftmost column whose last event ends at or
    before this event's start. ``total_columns`` is the overall maximum, so
    every event in the day uses the same horizontal slot width. This is a
    simpler approximation of Google's algorithm but eliminates visual
    overlap in the common case.
    """
    sorted_events = sorted(events, key=lambda e: (e.start, e.end))
    columns: list[list[Event]] = []
    placement: dict[str, int] = {}
    for ev in sorted_events:
        placed = False
        for idx, col in enumerate(columns):
            if not col or col[-1].end <= ev.start:
                col.append(ev)
                placement[ev.id] = idx
                placed = True
                break
        if not placed:
            columns.append([ev])
            placement[ev.id] = len(columns) - 1
    total = max(1, len(columns))
    return [(ev, placement[ev.id], total) for ev in sorted_events]


class CalendarView(ft.Container):
    def __init__(
        self,
        *,
        week_start: str = "sunday",
        default_view: str = "month",
        on_day_tap: OnDayTap | None = None,
        on_event_tap: OnEventTap | None = None,
    ) -> None:
        self._week_start = 6 if week_start == "sunday" else 0  # Python: Mon=0, Sun=6
        self._cal = Calendar(firstweekday=self._week_start)
        self._on_day_tap = on_day_tap
        self._on_event_tap = on_event_tap
        self._view_mode = default_view  # "month" or "week"
        self._cursor = date.today()
        self._events_by_day: dict[date, list[Event]] = defaultdict(list)

        # The week view's time grid is now anchored at ``theme.GRID_START_HOUR``
        # so there's no need to auto-scroll past midnight any more. The user
        # opens straight on the first visible hour (7 AM by default).

        # Header (Today button + arrows + month label + view toggle).
        # Matches Google Calendar: [Today] [<] [>]   <header>          [Toggle]
        self._header_text = ft.Text(
            "", color=theme.TEXT, size=28, weight=ft.FontWeight.W_500
        )
        # Shared style for the two chip-shaped header buttons (Today, view toggle).
        _chip_style = ft.ButtonStyle(
            side=ft.BorderSide(1, theme.DIVIDER),
            shape=ft.RoundedRectangleBorder(radius=8),
            padding=ft.Padding.symmetric(horizontal=14, vertical=8),
        )
        self._today_btn = ft.OutlinedButton(
            content=ft.Text("Today", color=theme.TEXT, size=14),
            on_click=self._go_today,
            style=_chip_style,
        )
        # Keep a handle on the inner Text so ``_toggle_view`` can flip the
        # label without rebuilding the button.
        self._toggle_label = ft.Text(
            "Week" if default_view == "month" else "Month",
            color=theme.TEXT,
            size=14,
        )
        self._toggle_btn = ft.OutlinedButton(
            content=self._toggle_label,
            on_click=self._toggle_view,
            style=_chip_style,
        )
        header = ft.Row(
            controls=[
                self._today_btn,
                ft.IconButton(
                    icon=ft.Icons.CHEVRON_LEFT,
                    icon_color=theme.TEXT,
                    on_click=self._prev,
                ),
                ft.IconButton(
                    icon=ft.Icons.CHEVRON_RIGHT,
                    icon_color=theme.TEXT,
                    on_click=self._next,
                ),
                ft.Container(
                    content=self._header_text,
                    expand=True,
                    alignment=ft.Alignment.CENTER,
                ),
                self._toggle_btn,
            ],
            spacing=8,
        )

        self._grid = ft.Column(spacing=4, expand=True)

        super().__init__(
            content=ft.Column(
                controls=[header, self._grid],
                spacing=8,
                expand=True,
            ),
            bgcolor=theme.SURFACE,
            border_radius=theme.CARD_RADIUS,
            padding=16,
            expand=True,
        )
        self._render()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def set_events(self, events: list[Event]) -> None:
        self._events_by_day = defaultdict(list)
        for ev in events:
            self._events_by_day[ev.start.date()].append(ev)
        self._render()

    def events_on(self, day: date) -> list[Event]:
        return list(self._events_by_day.get(day, []))

    def window_bounds(self) -> tuple[date, date]:
        """The date range (inclusive start, exclusive end) currently visible."""
        if self._view_mode == "week":
            start = self._start_of_week(self._cursor)
            return start, start + timedelta(days=7)
        first = self._cursor.replace(day=1)
        weeks = list(self._cal.monthdatescalendar(first.year, first.month))
        start = weeks[0][0]
        end = weeks[-1][-1] + timedelta(days=1)
        return start, end

    # The app shell installs this so it can re-fetch events when the user pages.
    _on_window_change: Callable[[], None] | None = None

    def install_window_callback(self, cb: Callable[[], None]) -> None:
        self._on_window_change = cb

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------
    def _start_of_week(self, d: date) -> date:
        sunday_start = self._week_start == 6
        if sunday_start:
            delta = (d.weekday() + 1) % 7
        else:
            delta = d.weekday()
        return d - timedelta(days=delta)

    def _prev(self, _e: ft.ControlEvent) -> None:
        if self._view_mode == "week":
            self._cursor -= timedelta(days=7)
        else:
            self._cursor = (
                self._cursor.replace(day=1) - timedelta(days=1)
            ).replace(day=1)
        self._render()
        if self._on_window_change:
            self._on_window_change()

    def _next(self, _e: ft.ControlEvent) -> None:
        if self._view_mode == "week":
            self._cursor += timedelta(days=7)
        else:
            first = self._cursor.replace(day=1)
            # Jump 32 days then snap back to the 1st - sidesteps month-length math.
            self._cursor = (first + timedelta(days=32)).replace(day=1)
        self._render()
        if self._on_window_change:
            self._on_window_change()

    def _toggle_view(self, _e: ft.ControlEvent) -> None:
        # View toggles preserve ``_cursor`` so paging in one view doesn't
        # snap back when you switch to the other. Use the "Today" button to
        # jump to the current week / month explicitly.
        self._view_mode = "week" if self._view_mode == "month" else "month"
        self._toggle_label.value = "Month" if self._view_mode == "week" else "Week"
        self._render()
        if self._on_window_change:
            self._on_window_change()

    def _go_today(self, _e: ft.ControlEvent) -> None:
        """Jump the cursor to today and re-render in the current view mode."""
        today = date.today()
        if self._cursor == today:
            return  # already on the current week / month; nothing to fetch
        self._cursor = today
        self._render()
        if self._on_window_change:
            self._on_window_change()

    # ------------------------------------------------------------------
    # Top-level render switch
    # ------------------------------------------------------------------
    def _render(self) -> None:
        if self._view_mode == "week":
            self._header_text.value = self._week_header()
            self._grid.controls = self._render_week()
        else:
            self._header_text.value = self._cursor.strftime("%B %Y")
            self._grid.controls = self._render_month()
        safe_update(self)

    def _week_header(self) -> str:
        start = self._start_of_week(self._cursor)
        end = start + timedelta(days=6)
        if start.month == end.month:
            return f"{start.strftime('%B')} {start.day}\u2013{end.day}, {end.year}"
        return f"{start.strftime('%b %d')} \u2013 {end.strftime('%b %d, %Y')}"

    # ==================================================================
    # MONTH VIEW
    # ==================================================================
    def _render_month(self) -> list[ft.Control]:
        rows: list[ft.Control] = [self._month_day_labels()]
        weeks = list(self._cal.monthdatescalendar(self._cursor.year, self._cursor.month))
        for week in weeks:
            rows.append(
                ft.Row(
                    controls=[
                        self._month_day_cell(
                            d, in_focus_month=(d.month == self._cursor.month)
                        )
                        for d in week
                    ],
                    spacing=4,
                    expand=True,
                )
            )
        return rows

    def _month_day_labels(self) -> ft.Row:
        labels = (
            ["S", "M", "T", "W", "T", "F", "S"]
            if self._week_start == 6
            else ["M", "T", "W", "T", "F", "S", "S"]
        )
        return ft.Row(
            controls=[
                ft.Container(
                    content=ft.Text(
                        lbl,
                        color=theme.TEXT_MUTED,
                        size=13,
                        text_align=ft.TextAlign.CENTER,
                    ),
                    expand=True,
                    alignment=ft.Alignment.CENTER,
                )
                for lbl in labels
            ],
            spacing=4,
        )

    def _month_day_cell(self, d: date, *, in_focus_month: bool) -> ft.Control:
        today = date.today()
        is_today = d == today
        events = self._events_by_day.get(d, [])

        number = ft.Text(
            str(d.day),
            color=(
                theme.ON_PRIMARY
                if is_today
                else (theme.TEXT if in_focus_month else theme.TEXT_DIM)
            ),
            size=16,
            weight=ft.FontWeight.W_600 if is_today else ft.FontWeight.W_400,
        )
        number_container = ft.Container(
            content=number,
            width=32,
            height=32,
            bgcolor=theme.TODAY_FILL if is_today else None,
            border_radius=16,
            alignment=ft.Alignment.CENTER,
        )

        max_titles = 3
        title_controls: list[ft.Control] = []
        for ev in events[:max_titles]:
            title_controls.append(self._month_event_pill(ev, in_focus_month=in_focus_month))
        if len(events) > max_titles:
            title_controls.append(
                ft.Text(
                    f"+{len(events) - max_titles} more",
                    color=theme.TEXT_MUTED,
                    size=10,
                    weight=ft.FontWeight.W_500,
                )
            )

        cell_body = ft.Column(
            controls=[
                ft.Row([number_container], alignment=ft.MainAxisAlignment.START),
                ft.Column(controls=title_controls, spacing=2, tight=True),
            ],
            spacing=4,
            tight=True,
        )

        return ft.Container(
            content=cell_body,
            padding=ft.Padding.symmetric(horizontal=6, vertical=6),
            height=110,
            expand=True,
            border_radius=8,
            bgcolor=ft.Colors.with_opacity(0.05, ft.Colors.WHITE) if in_focus_month else None,
            on_click=lambda _e, day=d: self._on_day_tap(day) if self._on_day_tap else None,
            ink=True,
        )

    def _month_event_pill(self, ev: Event, *, in_focus_month: bool) -> ft.Control:
        def _on_tap(_e: ft.ControlEvent, event: Event = ev) -> None:
            if self._on_event_tap is not None:
                self._on_event_tap(event)
            elif self._on_day_tap is not None:
                self._on_day_tap(event.start.date())

        return ft.Container(
            content=ft.Text(
                ev.title,
                color=theme.TEXT if in_focus_month else theme.TEXT_DIM,
                size=11,
                max_lines=1,
                overflow=ft.TextOverflow.ELLIPSIS,
            ),
            bgcolor=ft.Colors.with_opacity(
                0.40 if in_focus_month else 0.20, theme.PRIMARY
            ),
            padding=ft.Padding.symmetric(horizontal=6, vertical=2),
            border_radius=4,
            on_click=_on_tap,
            ink=True,
        )

    # ==================================================================
    # WEEK VIEW (Google-Calendar-style time grid)
    # ==================================================================
    def _render_week(self) -> list[ft.Control]:
        start = self._start_of_week(self._cursor)
        days = [start + timedelta(days=i) for i in range(7)]

        header_row = self._week_day_header(days)
        all_day_row = self._week_all_day_row(days)
        grid = self._week_time_grid(days)

        return [header_row, all_day_row, grid]

    def _week_day_header(self, days: list[date]) -> ft.Row:
        today = date.today()
        controls: list[ft.Control] = [
            ft.Container(width=theme.TIME_GUTTER),
        ]
        for d in days:
            short, num = _short_day_label(d)
            is_today = d == today
            controls.append(
                ft.Container(
                    expand=True,
                    alignment=ft.Alignment.CENTER,
                    padding=ft.Padding.symmetric(vertical=4),
                    content=ft.Column(
                        spacing=2,
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        tight=True,
                        controls=[
                            ft.Text(
                                short.upper(),
                                color=theme.TEXT_MUTED,
                                size=11,
                                weight=ft.FontWeight.W_600,
                            ),
                            ft.Container(
                                width=36,
                                height=36,
                                bgcolor=theme.TODAY_FILL if is_today else None,
                                border_radius=18,
                                alignment=ft.Alignment.CENTER,
                                content=ft.Text(
                                    num,
                                    color=theme.ON_PRIMARY if is_today else theme.TEXT,
                                    size=18,
                                    weight=(
                                        ft.FontWeight.W_600
                                        if is_today
                                        else ft.FontWeight.W_400
                                    ),
                                ),
                            ),
                        ],
                    ),
                )
            )
        return ft.Row(controls=controls, spacing=0)

    def _week_all_day_row(self, days: list[date]) -> ft.Control:
        """A compact strip for all-day events, one short pill per event."""
        controls: list[ft.Control] = [
            ft.Container(
                width=theme.TIME_GUTTER,
                alignment=ft.Alignment.CENTER_RIGHT,
                padding=ft.Padding.only(right=6, top=2, bottom=2),
                content=ft.Text(
                    "all-day",
                    color=theme.TEXT_DIM,
                    size=10,
                    text_align=ft.TextAlign.RIGHT,
                ),
            ),
        ]
        max_visible = 2
        for d in days:
            all_days = [ev for ev in self._events_by_day.get(d, []) if ev.all_day]
            cell_children: list[ft.Control] = []
            for ev in all_days[:max_visible]:
                cell_children.append(self._all_day_pill(ev))
            if len(all_days) > max_visible:
                cell_children.append(
                    ft.Text(
                        f"+{len(all_days) - max_visible}",
                        color=theme.TEXT_MUTED,
                        size=10,
                    )
                )
            controls.append(
                ft.Container(
                    expand=True,
                    padding=ft.Padding.symmetric(horizontal=2, vertical=2),
                    content=ft.Column(
                        controls=cell_children,
                        spacing=2,
                        tight=True,
                    ),
                )
            )
        return ft.Container(
            content=ft.Row(controls=controls, spacing=0),
            border=ft.Border.only(
                bottom=ft.BorderSide(1, theme.DIVIDER),
            ),
            padding=ft.Padding.only(bottom=4),
        )

    def _all_day_pill(self, ev: Event) -> ft.Control:
        def _on_tap(_e: ft.ControlEvent, event: Event = ev) -> None:
            if self._on_event_tap is not None:
                self._on_event_tap(event)

        return ft.Container(
            content=ft.Text(
                ev.title,
                color=theme.TEXT,
                size=11,
                weight=ft.FontWeight.W_500,
                max_lines=1,
                overflow=ft.TextOverflow.ELLIPSIS,
            ),
            bgcolor=ft.Colors.with_opacity(0.50, theme.PRIMARY),
            padding=ft.Padding.symmetric(horizontal=6, vertical=2),
            border_radius=4,
            on_click=_on_tap,
            ink=True,
        )

    def _week_time_grid(self, days: list[date]) -> ft.Control:
        """The scrollable area: time-gutter + 7 day-stack columns.

        Renders ``theme.GRID_HOURS`` hours starting from
        ``theme.GRID_START_HOUR`` (default 7AM, ending at midnight). The
        scrollable column still supports overflow scrolling so a user with a
        very short screen can pan through the visible window.
        """
        time_gutter = self._hour_gutter()
        day_columns = [self._day_column(d) for d in days]
        time_row = ft.Row(
            controls=[time_gutter, *day_columns],
            spacing=0,
            vertical_alignment=ft.CrossAxisAlignment.START,
        )
        return ft.Column(
            scroll=ft.ScrollMode.AUTO,
            expand=True,
            controls=[time_row],
        )

    def _hour_gutter(self) -> ft.Control:
        labels: list[ft.Control] = []
        for h in range(theme.GRID_START_HOUR, theme.GRID_END_HOUR):
            # Suppress the very first label so the top edge looks cleaner
            # (matches Google Calendar's behaviour at the start of its grid).
            is_first = h == theme.GRID_START_HOUR
            labels.append(
                ft.Container(
                    height=theme.HOUR_HEIGHT,
                    width=theme.TIME_GUTTER,
                    padding=ft.Padding.only(right=6, top=2),
                    alignment=ft.Alignment.TOP_RIGHT,
                    content=(
                        None
                        if is_first
                        else ft.Text(
                            _fmt_hour_label(h),
                            color=theme.TEXT_DIM,
                            size=10,
                        )
                    ),
                )
            )
        return ft.Column(controls=labels, spacing=0, tight=True)

    def _day_column(self, d: date) -> ft.Control:
        """A ``GRID_HOURS``-tall Stack for a single day, anchored at
        ``GRID_START_HOUR``.

        The Stack's children fall into these layers:

        1. Background tint (today only)
        2. Hour gridlines (one per visible hour)
        3. A click-target overlay that catches taps in empty space
        4. A Row of N "overlap sub-columns", each a Stack with the
           absolutely-positioned event blocks assigned to that overlap slot.
        5. The "now" line on today's column (only when we're inside the
           visible window).
        """
        today = date.today()
        is_today = d == today
        total_h = theme.GRID_TOTAL_HEIGHT

        children: list[ft.Control] = []

        # 1. Today background tint
        if is_today:
            children.append(
                ft.Container(
                    left=0,
                    right=0,
                    top=0,
                    height=total_h,
                    bgcolor=ft.Colors.with_opacity(0.08, theme.PRIMARY),
                )
            )

        # 2. Hour gridlines, one per visible hour.
        for i in range(theme.GRID_HOURS):
            children.append(
                ft.Container(
                    left=0,
                    right=0,
                    top=i * theme.HOUR_HEIGHT,
                    height=1,
                    bgcolor=theme.GRIDLINE,
                )
            )

        # 3. Empty-area click target -> day summary sheet.
        children.append(
            ft.Container(
                left=0,
                right=0,
                top=0,
                height=total_h,
                bgcolor=ft.Colors.TRANSPARENT,
                on_click=(
                    (lambda _e, day=d: self._on_day_tap(day))
                    if self._on_day_tap
                    else None
                ),
            )
        )

        # 4. Event blocks, split into overlap-columns.
        timed = [ev for ev in self._events_by_day.get(d, []) if not ev.all_day]
        if timed:
            children.append(self._event_layer(timed, total_h))

        # 5. "Now" line on today, only when we're inside the visible window.
        if is_today:
            now = datetime.now()
            now_offset_h = now.hour + now.minute / 60.0
            if theme.GRID_START_HOUR <= now_offset_h < theme.GRID_END_HOUR:
                now_top = (now_offset_h - theme.GRID_START_HOUR) * theme.HOUR_HEIGHT
                children.append(
                    ft.Container(
                        left=0,
                        right=0,
                        top=now_top,
                        height=2,
                        bgcolor=ft.Colors.RED_ACCENT_400,
                    )
                )

        return ft.Container(
            expand=True,
            content=ft.Stack(
                controls=children,
                height=total_h,
            ),
            border=ft.Border.only(
                left=ft.BorderSide(1, theme.GRIDLINE),
            ),
        )

    def _event_layer(self, timed: list[Event], total_h: int) -> ft.Control:
        """Render every timed event for one day as a Row of overlap-columns.

        Each Row child is a Stack (expand=1, so all children share the day
        column's width equally). Inside each Stack, individual events are
        absolute-positioned by ``top`` and ``height``.
        """
        packed = _pack_overlapping(timed)
        total_cols = packed[0][2] if packed else 1
        column_stacks: list[list[ft.Control]] = [[] for _ in range(total_cols)]
        for ev, col_idx, _total in packed:
            block = self._event_block(ev)
            if block is not None:
                column_stacks[col_idx].append(block)

        row = ft.Row(
            spacing=2,
            vertical_alignment=ft.CrossAxisAlignment.START,
            controls=[
                ft.Container(
                    expand=True,
                    content=ft.Stack(
                        controls=stack_children,
                        height=total_h,
                    ),
                )
                for stack_children in column_stacks
            ],
        )
        # Position the row to fill its parent Stack horizontally; it takes its
        # height from ``height=total_h`` since Stack children with positional
        # props are sized explicitly.
        return ft.Container(
            left=0,
            right=0,
            top=0,
            height=total_h,
            content=row,
        )

    def _event_block(self, ev: Event) -> ft.Control | None:
        """Absolute-positioned event card; horizontal slot handled by parent.

        Events are clipped to the visible window
        ``[GRID_START_HOUR, GRID_END_HOUR)``. Events fully outside the window
        return ``None`` (the day-summary sheet still surfaces them).
        """
        day_start = datetime.combine(
            ev.start.date(), time.min, tzinfo=ev.start.tzinfo
        )
        window_start = day_start + timedelta(hours=theme.GRID_START_HOUR)
        window_end = day_start + timedelta(hours=theme.GRID_END_HOUR)

        start_dt = max(ev.start, window_start)
        end_dt = min(ev.end, window_end)
        if end_dt <= start_dt:
            return None
        start_offset_h = (start_dt - window_start).total_seconds() / 3600.0
        duration_h = (end_dt - start_dt).total_seconds() / 3600.0
        top = start_offset_h * theme.HOUR_HEIGHT
        height = max(24, duration_h * theme.HOUR_HEIGHT)

        return ft.Container(
            top=top,
            left=0,
            right=0,
            height=height,
            padding=ft.Padding.symmetric(horizontal=6, vertical=4),
            bgcolor=ft.Colors.with_opacity(0.85, theme.PRIMARY),
            border_radius=6,
            content=ft.Column(
                spacing=1,
                tight=True,
                controls=[
                    ft.Text(
                        ev.title,
                        color=theme.ON_PRIMARY,
                        size=12,
                        weight=ft.FontWeight.W_600,
                        max_lines=2,
                        overflow=ft.TextOverflow.ELLIPSIS,
                    ),
                    ft.Text(
                        ev.start.strftime("%I:%M %p").lstrip("0"),
                        color=ft.Colors.with_opacity(0.85, ft.Colors.WHITE),
                        size=10,
                        max_lines=1,
                        overflow=ft.TextOverflow.ELLIPSIS,
                    ),
                ],
            ),
            on_click=(
                (lambda _e, event=ev: self._on_event_tap(event))
                if self._on_event_tap
                else None
            ),
            ink=True,
        )
