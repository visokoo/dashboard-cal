"""Flet app shell: layout, kiosk window setup, refresh loops, idle cursor."""

from __future__ import annotations

import asyncio
import logging
from datetime import date
from pathlib import Path

import flet as ft

from . import theme
from .auth import GoogleAuth, OAuthError
from .config import GeocodeResult, Settings, geocode_zip, load_settings
from .services.calendar import CalendarService, Event
from .services.tasks import TasksService
from .services.todos import TodoStore
from .services.weather import fetch_forecast
from .ui.background import Background
from .ui.calendar_view import CalendarView
from .ui.clock import Clock
from .ui.event_sheet import EventSheet
from .ui.weather_strip import WeatherStrip

# NOTE: The Todos/Grocery side panel (``ui.side_panel``) is intentionally not
# imported here. Its UI is hidden for now; the underlying ``TodoStore`` and
# ``TasksService`` services are still wired so the data layer keeps working
# and the panel can be re-enabled without losing state.

log = logging.getLogger(__name__)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


class DashboardApp:
    """Owns service objects + UI controls. One instance per Flet page."""

    def __init__(self, *, force_reauth: bool = False) -> None:
        self.settings: Settings = load_settings()
        self.todos = TodoStore()

        # Geocode happens on import-time call from main loop; here we just resolve
        # the cached value (or trigger a one-shot lookup). Failures bubble up so
        # the user sees a clear startup error.
        self.location: GeocodeResult = geocode_zip(self.settings.weather)

        self._force_reauth = force_reauth
        self.calendar_svc: CalendarService | None = None
        self.tasks_svc: TasksService | None = None

        # UI controls (built in build_ui)
        self.background: Background | None = None
        self.weather_strip: WeatherStrip | None = None
        self.calendar_view: CalendarView | None = None
        self.event_sheet: EventSheet | None = None
        self.clock: Clock | None = None

    # ------------------------------------------------------------------
    # auth (lazy)
    # ------------------------------------------------------------------
    def _try_init_google(self) -> None:
        try:
            auth = GoogleAuth(_project_root() / "credentials.json")
            creds = auth.get_credentials(force_reauth=self._force_reauth)
        except OAuthError as e:
            # Don't echo internal details to the UI; show generic copy.
            log.warning("auth: skipping Google services (%s)", type(e).__name__)
            return
        except Exception as e:
            # Don't ``log.exception`` here: the traceback may carry OAuth
            # client identifiers or other token-adjacent metadata. The type
            # is enough to triage.
            log.warning("auth: unexpected failure type=%s", type(e).__name__)
            return
        self.calendar_svc = CalendarService(creds, self.settings.calendar.calendars)
        self.tasks_svc = TasksService(creds, self.settings.tasks.list_name)
        log.info("auth: Google services initialized")

    # ------------------------------------------------------------------
    # UI build
    # ------------------------------------------------------------------
    async def main(self, page: ft.Page) -> None:
        page.title = "dashboard-cal"
        # Flet 0.85: Theme.theme is the light-mode theme; dark_theme is dark-mode.
        # Set both to the same seed so the look is consistent regardless of mode.
        built = theme.build_theme()
        page.theme = built
        page.dark_theme = built
        page.theme_mode = (
            ft.ThemeMode.DARK if self.settings.ui.theme != "light" else ft.ThemeMode.LIGHT
        )
        page.padding = 0
        page.bgcolor = ft.Colors.BLACK
        page.fonts = {"Roboto": "https://fonts.gstatic.com/s/roboto/v30/KFOmCnqEu92Fr1Mu4mxKKTU1Kg.woff2"}

        if self.settings.ui.fullscreen:
            page.window.full_screen = True
            page.window.frameless = True
            page.window.always_on_top = True
        else:
            page.window.width = 1440
            page.window.height = 960

        # Build & mount UI before kicking off network calls.
        self.background = Background(self.settings.photos)
        self.weather_strip = WeatherStrip()
        self.clock = Clock(use_24h=False)
        # BottomSheet is a DialogControl in Flet 0.85+. It must NOT be placed
        # in page.controls; instead it is shown via page.show_dialog(sheet).
        self.event_sheet = EventSheet()
        self.calendar_view = CalendarView(
            week_start=self.settings.calendar.week_start,
            default_view=self.settings.calendar.default_view,
            on_day_tap=self._on_day_tap,
            on_event_tap=self._on_event_tap,
        )
        self.calendar_view.install_window_callback(
            lambda: page.run_task(self._refresh_calendar)
        )

        page.add(self._compose())

        # Initial state without network:
        self.background.start(page)
        self.clock.start(page)

        # Now bring up Google services and start refresh loops.
        self._try_init_google()

        await asyncio.gather(
            self._refresh_calendar(),
            self._refresh_weather(),
        )

        page.run_task(self._loop_calendar)
        page.run_task(self._loop_weather)

    def _compose(self) -> ft.Control:
        # Top row: clock (left) + weather strip (rest of the width). The
        # Todos/Grocery side panel has been removed for now so the calendar
        # grid below has room for event titles.
        weather_bar = ft.Container(
            content=self.weather_strip,
            padding=12,
            bgcolor=theme.SURFACE_LOW,
            border_radius=theme.CARD_RADIUS,
            expand=True,
        )
        top_row = ft.Container(
            content=ft.Row(
                spacing=16,
                vertical_alignment=ft.CrossAxisAlignment.STRETCH,
                controls=[
                    ft.Container(content=self.clock, width=320),
                    weather_bar,
                ],
            ),
            height=140,
        )

        foreground = ft.Container(
            content=ft.Column(
                controls=[
                    top_row,
                    ft.Container(content=self.calendar_view, expand=True),
                ],
                spacing=16,
                expand=True,
            ),
            padding=16,
            expand=True,
        )

        # Stack the photo background under the foreground.
        return ft.Stack(
            controls=[self.background, foreground],
            expand=True,
        )

    # ------------------------------------------------------------------
    # event handling
    # ------------------------------------------------------------------
    def _on_day_tap(self, day: date) -> None:
        if not self.calendar_view or not self.event_sheet:
            return
        events = self.calendar_view.events_on(day)
        page = self.calendar_view.page
        if page:
            self.event_sheet.show(page, day, events)

    def _on_event_tap(self, ev: Event) -> None:
        if not self.calendar_view or not self.event_sheet:
            return
        page = self.calendar_view.page
        if page:
            self.event_sheet.show_event(page, ev)

    # ------------------------------------------------------------------
    # refresh loops
    # ------------------------------------------------------------------
    async def _refresh_calendar(self) -> None:
        if not self.calendar_svc or not self.calendar_view:
            return
        start, end = self.calendar_view.window_bounds()
        try:
            events: list[Event] = await self.calendar_svc.list_events(start, end)
        except Exception as e:
            # ``log.exception`` would dump the underlying googleapiclient
            # traceback, which embeds the request URL (and therefore the
            # calendar id, which is semi-sensitive PII). Status codes are
            # logged inside CalendarService; here we record only the type.
            log.warning("calendar: refresh failed type=%s", type(e).__name__)
            return
        self.calendar_view.set_events(events)

    async def _refresh_weather(self) -> None:
        if not self.weather_strip:
            return
        loop = asyncio.get_running_loop()
        days = await loop.run_in_executor(
            None, fetch_forecast, self.settings.weather, self.location
        )
        self.weather_strip.update_forecast(days)

    async def _loop_calendar(self) -> None:
        await asyncio.sleep(self.settings.ui.refresh.calendar_seconds)
        while True:
            await self._refresh_calendar()
            await asyncio.sleep(self.settings.ui.refresh.calendar_seconds)

    async def _loop_weather(self) -> None:
        await asyncio.sleep(self.settings.ui.refresh.weather_seconds)
        while True:
            await self._refresh_weather()
            await asyncio.sleep(self.settings.ui.refresh.weather_seconds)


def run(*, force_reauth: bool = False) -> None:
    """Entry point: create the app and hand it to Flet."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    app = DashboardApp(force_reauth=force_reauth)
    # Flet 1.0 (0.70+) entry point is ft.run(main_async_fn).
    ft.run(app.main)
