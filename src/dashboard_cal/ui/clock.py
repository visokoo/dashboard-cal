"""Large digital clock with date subline.

Designed for the bottom-left of the dashboard. Updates once a second from
``Page.run_task`` so it never blocks the UI thread, and uses cross-platform
``strftime`` directives (no POSIX ``%-I``/``%-d``).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

import flet as ft

from .. import theme
from ._util import safe_update

log = logging.getLogger(__name__)


def _fmt_time(now: datetime, *, use_24h: bool) -> str:
    if use_24h:
        return now.strftime("%H:%M")
    # ``%-I`` is POSIX-only and crashes on Windows. Use ``%I`` then strip the
    # leading zero ourselves so the same code runs on Linux/macOS/Windows.
    return now.strftime("%I:%M").lstrip("0") or "12:00"


def _fmt_date(now: datetime) -> str:
    # e.g. "Friday, May 15"; built without ``%-d`` so it works on Windows.
    return f"{now.strftime('%A, %B')} {now.day}"


def _fmt_meridian(now: datetime) -> str:
    return now.strftime("%p")


class Clock(ft.Container):
    """Time on top, date underneath, optional AM/PM suffix."""

    def __init__(self, *, use_24h: bool = False) -> None:
        self._use_24h = use_24h
        self._time = ft.Text(
            value=_fmt_time(datetime.now(), use_24h=use_24h),
            color=theme.TEXT,
            size=88,
            weight=ft.FontWeight.W_300,
        )
        self._meridian = ft.Text(
            value="" if use_24h else _fmt_meridian(datetime.now()),
            color=theme.TEXT_MUTED,
            size=24,
            weight=ft.FontWeight.W_500,
        )
        self._date = ft.Text(
            value=_fmt_date(datetime.now()),
            color=theme.TEXT_MUTED,
            size=18,
        )

        time_row = ft.Row(
            controls=[self._time, self._meridian],
            spacing=8,
            vertical_alignment=ft.CrossAxisAlignment.END,
            tight=True,
        )
        body = ft.Column(
            spacing=2,
            controls=[time_row, self._date],
            tight=True,
        )
        super().__init__(
            content=body,
            padding=ft.Padding.only(left=20, right=20, top=12, bottom=12),
            bgcolor=theme.SURFACE_LOW,
            border_radius=theme.CARD_RADIUS,
        )

    def start(self, page: ft.Page) -> None:
        page.run_task(self._loop)

    async def _loop(self) -> None:
        # We wake once a second so AM/PM transitions and the date roll-over
        # appear promptly; the rendered string itself only changes on the
        # minute boundary (or at noon/midnight).
        while True:
            try:
                now = datetime.now()
                self._time.value = _fmt_time(now, use_24h=self._use_24h)
                self._meridian.value = (
                    "" if self._use_24h else _fmt_meridian(now)
                )
                self._date.value = _fmt_date(now)
                safe_update(self)
            except Exception:
                # A failed tick must not kill the loop; the UI will catch up
                # on the next iteration. Don't log payload details.
                log.exception("clock: update tick failed")
            await asyncio.sleep(1.0)
