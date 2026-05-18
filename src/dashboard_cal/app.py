"""Flet app shell: layout, kiosk window setup, refresh loops."""

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
from .ui._util import safe_update
from .ui.background import Background
from .ui.calendar_view import CalendarView
from .ui.clock import Clock
from .ui.event_sheet import EventSheet
from .ui.side_panel import GroceryPanel, TodosPanel
from .ui.tasks_modal import TasksModal
from .ui.weather_strip import WeatherStrip

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

        # UI controls (built in main(); None until then so we don't accidentally
        # touch Flet APIs before the page exists).
        self.background: Background | None = None
        self.weather_strip: WeatherStrip | None = None
        self.calendar_view: CalendarView | None = None
        self.event_sheet: EventSheet | None = None
        self.clock: Clock | None = None
        self.todos_panel: TodosPanel | None = None
        self.grocery_panel: GroceryPanel | None = None
        self.tasks_modal: TasksModal | None = None
        # Small red dot overlaid on the tasks button when either checklist
        # has at least one unchecked item. Built in ``_compose``; mutated
        # from ``_update_tasks_badge``.
        self._tasks_badge: ft.Container | None = None
        # Reference to the modal's close (X) button. We focus this on
        # modal-close to pull focus off any focused TextField so the OS
        # touch keyboard dismisses cleanly.
        self._tasks_close_btn: ft.IconButton | None = None

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

        # Tasks / grocery side panels and the slide-in modal that hosts them.
        # ``on_change`` lets each panel notify us when its data shifts so we
        # can keep the tasks-button badge in sync without a polling loop.
        self.todos_panel = TodosPanel(self.todos, on_change=self._update_tasks_badge)
        self.grocery_panel = GroceryPanel(
            tasks=None,
            run_async=page.run_task,
            on_change=self._update_tasks_badge,
        )
        # Scrim taps route through ``_close_tasks`` (same handler as the
        # X button) so both close paths share the keyboard-focus cleanup.
        self.tasks_modal = TasksModal(
            self._build_tasks_panel_content(),
            on_dismiss=self._close_tasks,
        )

        page.add(self._compose())

        # Initial state without network:
        self.background.start(page)
        self.clock.start(page)
        # Local todos load synchronously from SQLite.
        self.todos_panel.refresh()

        # Now bring up Google services and start refresh loops.
        self._try_init_google()
        if self.tasks_svc and self.grocery_panel is not None:
            self.grocery_panel.set_service(self.tasks_svc)

        await asyncio.gather(
            self._refresh_calendar(),
            self._refresh_weather(),
            self._refresh_grocery(),
        )

        page.run_task(self._loop_calendar)
        page.run_task(self._loop_weather)
        page.run_task(self._loop_grocery)

    def _compose(self) -> ft.Control:
        # Top row: clock (left) + weather strip (middle, expanding) + tasks
        # button (right). Tapping the tasks button is the only way to open
        # the tasks modal -- there is intentionally no swipe gesture.
        weather_bar = ft.Container(
            content=self.weather_strip,
            padding=12,
            bgcolor=theme.SURFACE_LOW,
            border_radius=theme.CARD_RADIUS,
            expand=True,
        )

        # Small red notification dot pinned to the top-right corner of the
        # tasks button. Positioning is on the badge itself (right/top) so
        # the Stack doesn't need a wrapping container. ``visible`` toggles
        # in ``_update_tasks_badge``.
        self._tasks_badge = ft.Container(
            width=12,
            height=12,
            bgcolor=theme.ERROR,
            border_radius=6,
            visible=False,
            right=14,
            top=14,
        )

        # Whole card is the hit target -- ``on_click`` + ``ink=True`` give
        # the 72px-wide card a Material ripple. ``Stack.alignment`` centers
        # the icon; the badge stays in its top-right corner because it has
        # explicit ``right``/``top`` set above.
        tasks_btn = ft.Container(
            content=ft.Stack(
                controls=[
                    ft.Icon(ft.Icons.CHECKLIST, color=theme.TEXT, size=28),
                    self._tasks_badge,
                ],
                alignment=ft.Alignment.CENTER,
                expand=True,
            ),
            width=72,
            bgcolor=theme.SURFACE_LOW,
            border_radius=theme.CARD_RADIUS,
            on_click=self._open_tasks,
            ink=True,
            tooltip="Open tasks",
        )
        top_row = ft.Container(
            content=ft.Row(
                spacing=16,
                vertical_alignment=ft.CrossAxisAlignment.STRETCH,
                controls=[
                    ft.Container(content=self.clock, width=320),
                    weather_bar,
                    tasks_btn,
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

        # Stack order: photo background, foreground, then the tasks modal
        # sits on top so its scrim + panel render above the calendar when
        # open.
        return ft.Stack(
            controls=[self.background, foreground, self.tasks_modal],
            expand=True,
        )

    def _build_tasks_panel_content(self) -> ft.Control:
        """Vertical layout for the slide-in tasks modal.

        Drawer header (title + close button) on top, then Todos, then a
        divider, then Grocery. ``Column.scroll`` keeps the whole thing
        scrollable if the user adds many items.
        """
        # Stash the close button on ``self`` so ``_close_tasks`` can
        # ``focus()`` it -- moving focus off the text fields inside the
        # panel forces the OS touch keyboard to dismiss.
        self._tasks_close_btn = ft.IconButton(
            icon=ft.Icons.CLOSE,
            icon_color=theme.TEXT_MUTED,
            on_click=self._close_tasks,
            tooltip="Close",
        )
        header = ft.Row(
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                ft.Text(
                    "Tasks",
                    color=theme.TEXT,
                    size=22,
                    weight=ft.FontWeight.W_600,
                    expand=True,
                ),
                self._tasks_close_btn,
            ],
        )
        return ft.Column(
            spacing=12,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
            controls=[
                header,
                ft.Divider(color=theme.DIVIDER, height=8),
                self.todos_panel,
                ft.Divider(color=theme.DIVIDER, height=16),
                self.grocery_panel,
            ],
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
    # tasks modal: open / close
    # ------------------------------------------------------------------
    def _open_tasks(self, _e: ft.ControlEvent | None = None) -> None:
        if self.tasks_modal is not None:
            self.tasks_modal.open()

    def _close_tasks(self, _e: ft.ControlEvent | None = None) -> None:
        if self.tasks_modal is None:
            return
        # Move keyboard focus to the close button (a non-text control)
        # so the OS touch keyboard dismisses. Without this, a focused
        # TextField inside the modal keeps the keyboard pinned open and
        # makes it re-assert on later calendar taps.
        if self._tasks_close_btn is not None and self._tasks_close_btn.page is not None:
            self._tasks_close_btn.page.run_task(self._tasks_close_btn.focus)
        self.tasks_modal.close()

    def _update_tasks_badge(self) -> None:
        """Show the dot iff either checklist has at least one unchecked item.

        Fires from both panels' ``on_change`` hooks after any mutation.
        """
        if self._tasks_badge is None:
            return
        unchecked = bool(
            (self.todos_panel and self.todos_panel.has_unchecked())
            or (self.grocery_panel and self.grocery_panel.has_unchecked())
        )
        if self._tasks_badge.visible != unchecked:
            self._tasks_badge.visible = unchecked
            safe_update(self._tasks_badge)

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

    async def _refresh_grocery(self) -> None:
        """Pull the latest grocery items from Google Tasks (if authed)."""
        if self.grocery_panel is None:
            return
        try:
            await self.grocery_panel.refresh()
        except Exception as e:
            # ``refresh()`` already swallows HttpError internally and logs
            # the status. This catch is a safety net for unexpected errors;
            # we log only the type per the logging-security rule.
            log.warning("grocery: refresh failed type=%s", type(e).__name__)

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

    async def _loop_grocery(self) -> None:
        await asyncio.sleep(self.settings.ui.refresh.tasks_seconds)
        while True:
            await self._refresh_grocery()
            await asyncio.sleep(self.settings.ui.refresh.tasks_seconds)


def run(*, force_reauth: bool = False) -> None:
    """Entry point: create the app and hand it to Flet."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    app = DashboardApp(force_reauth=force_reauth)
    # Flet 1.0 (0.70+) entry point is ft.run(main_async_fn).
    ft.run(app.main)
