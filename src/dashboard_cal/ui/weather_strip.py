"""Bottom forecast strip: N day cards from today forward."""

from __future__ import annotations

from datetime import date

import flet as ft

from .. import theme
from ..services.weather import DayForecast
from ._util import safe_update


class WeatherStrip(ft.Row):
    def __init__(self) -> None:
        super().__init__(
            spacing=12,
            alignment=ft.MainAxisAlignment.SPACE_EVENLY,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    def update_forecast(self, days: list[DayForecast]) -> None:
        self.controls = [self._card(d) for d in days]
        safe_update(self)

    def _card(self, day: DayForecast) -> ft.Container:
        label = "Today" if day.day == date.today() else day.day.strftime("%a")
        # DayForecast.icon is a snake_case Material icon name; ft.Icons exposes
        # the same icons as upper-case attributes.
        icon = getattr(ft.Icons, day.icon.upper(), ft.Icons.WB_SUNNY)
        return ft.Container(
            content=ft.Column(
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=4,
                controls=[
                    ft.Text(label, color=theme.TEXT, size=14, weight=ft.FontWeight.W_600),
                    ft.Icon(
                        icon=icon,
                        size=32,
                        color=theme.TEXT,
                    ),
                    ft.Text(
                        f"{round(day.high)}\u00B0 / {round(day.low)}\u00B0",
                        color=theme.TEXT,
                        size=14,
                    ),
                    ft.Text(
                        day.label,
                        color=theme.TEXT_MUTED,
                        size=11,
                        max_lines=1,
                        overflow=ft.TextOverflow.ELLIPSIS,
                    ),
                ],
            ),
            padding=12,
            bgcolor=theme.SURFACE,
            border_radius=theme.CARD_RADIUS,
            expand=True,
        )
