"""Reusable Todos and Google Tasks-backed Grocery checklist columns.

Each ``_ChecklistColumn`` is a vertical Todos/Grocery widget with a header,
a scrolling list, an input field, and an add-button. ``TodosPanel`` is
backed by the local SQLite ``TodoStore``; ``GroceryPanel`` is backed by
``TasksService`` (Google Tasks).

These columns are designed to be embedded into another container -- e.g.
the slide-in ``TasksModal`` -- which decides whether to stack them
vertically, place them side-by-side, or wrap them in tabs.
"""

from __future__ import annotations

import logging
from typing import Awaitable, Callable

import flet as ft

from .. import theme
from ..services.tasks import GroceryItem, TasksService
from ..services.todos import Todo, TodoStore
from ._util import safe_update

log = logging.getLogger(__name__)


class _ChecklistColumn(ft.Column):
    """Shared visual pattern: header, scrolling list, input row, FAB."""

    def __init__(self, title: str) -> None:
        self._title = ft.Text(title, size=20, color=theme.TEXT, weight=ft.FontWeight.W_600)
        self._list = ft.Column(spacing=4, scroll=ft.ScrollMode.AUTO, expand=True)
        self._input = ft.TextField(
            hint_text=f"Add to {title.lower()}...",
            border=ft.InputBorder.UNDERLINE,
            border_color=theme.DIVIDER,
            focused_border_color=theme.PRIMARY,
            text_style=ft.TextStyle(color=theme.TEXT, size=15),
            hint_style=ft.TextStyle(color=theme.TEXT_DIM, size=15),
            color=theme.TEXT,
            cursor_color=theme.PRIMARY,
            expand=True,
            dense=True,
        )
        self._add_btn = ft.IconButton(
            icon=ft.Icons.ADD_CIRCLE,
            icon_color=theme.PRIMARY,
            icon_size=32,
        )
        super().__init__(
            controls=[
                self._title,
                ft.Divider(color=theme.DIVIDER, height=8),
                self._list,
                ft.Row([self._input, self._add_btn], spacing=8),
            ],
            spacing=10,
            expand=True,
        )


class TodosPanel(_ChecklistColumn):
    def __init__(self, store: TodoStore) -> None:
        super().__init__("Todos")
        self._store = store
        self._input.on_submit = self._on_submit
        self._add_btn.on_click = self._on_submit

    def refresh(self) -> None:
        items = self._store.list()
        self._list.controls = [self._row(t) for t in items]
        safe_update(self)

    def _row(self, t: Todo) -> ft.Control:
        cb = ft.Checkbox(
            value=t.done,
            label=t.text,
            label_style=ft.TextStyle(
                color=theme.TEXT_DIM if t.done else theme.TEXT,
                size=15,
                decoration=(
                    ft.TextDecoration.LINE_THROUGH if t.done else ft.TextDecoration.NONE
                ),
            ),
            check_color=theme.ON_PRIMARY,
            fill_color=theme.PRIMARY,
            on_change=lambda e, todo_id=t.id: self._toggle(todo_id, bool(e.control.value)),
        )
        delete = ft.IconButton(
            icon=ft.Icons.CLOSE,
            icon_size=18,
            icon_color=theme.TEXT_DIM,
            on_click=lambda e, todo_id=t.id: self._delete(todo_id),
        )
        return ft.Row([cb, ft.Container(expand=True), delete],
                      spacing=4, vertical_alignment=ft.CrossAxisAlignment.CENTER)

    def _toggle(self, todo_id: int, done: bool) -> None:
        try:
            self._store.set_done(todo_id, done)
        except Exception as e:
            # ``log.exception`` here would carry a SQLite traceback that may
            # echo bound parameters. Log only the type (logging-security).
            log.warning("todos: toggle failed type=%s", type(e).__name__)
        self.refresh()

    def _delete(self, todo_id: int) -> None:
        try:
            self._store.delete(todo_id)
        except Exception as e:
            log.warning("todos: delete failed type=%s", type(e).__name__)
        self.refresh()

    def _on_submit(self, _e: ft.ControlEvent) -> None:
        text = (self._input.value or "").strip()
        if not text:
            return
        try:
            self._store.add(text)
        except ValueError:
            # Validation rejected the text - generic UI message, no raw exception shown.
            self._input.error_text = "Invalid text"
            safe_update(self)
            return
        self._input.value = ""
        self._input.error_text = None
        self.refresh()
        # ``TextField.focus`` is a coroutine in Flet 0.85+, so we can't
        # call it directly from a sync handler -- doing so triggers
        # "coroutine ... was never awaited". Schedule it via the page.
        page = self._input.page
        if page is not None:
            page.run_task(self._input.focus)


class GroceryPanel(_ChecklistColumn):
    """Google Tasks-backed grocery list. Operations are async and best-effort offline."""

    def __init__(
        self,
        tasks: TasksService | None,
        # ``run_async`` must accept a coroutine *function* (e.g. Flet's
        # ``page.run_task``), not a coroutine object. Passing a coroutine
        # produces "handler must be a coroutine function" at runtime.
        run_async: Callable[[Callable[[], Awaitable[None]]], object],
    ) -> None:
        super().__init__("Grocery")
        self._tasks = tasks
        self._run_async = run_async
        self._items: list[GroceryItem] = []
        self._input.on_submit = self._on_submit
        self._add_btn.on_click = self._on_submit
        if tasks is None:
            self._show_unavailable()

    def _show_unavailable(self) -> None:
        self._list.controls = [
            ft.Text(
                "Sign in to Google to enable grocery sync.",
                color=theme.TEXT_DIM, size=14, italic=True,
            )
        ]
        self._input.disabled = True
        self._add_btn.disabled = True

    def set_service(self, tasks: TasksService) -> None:
        self._tasks = tasks
        self._input.disabled = False
        self._add_btn.disabled = False

    async def refresh(self) -> None:
        if not self._tasks:
            return
        try:
            self._items = await self._tasks.list_items()
        except Exception as e:
            # Network/auth failure - keep last-known items. Don't ``log.exception``
            # because a googleapiclient traceback embeds the task-list URL
            # (which includes the list id, a semi-sensitive identifier).
            log.warning("grocery: refresh failed type=%s", type(e).__name__)
            return
        self._list.controls = [self._row(i) for i in self._items]
        safe_update(self)

    def _row(self, t: GroceryItem) -> ft.Control:
        cb = ft.Checkbox(
            value=t.done,
            label=t.title,
            label_style=ft.TextStyle(
                color=theme.TEXT_DIM if t.done else theme.TEXT,
                size=15,
                decoration=(
                    ft.TextDecoration.LINE_THROUGH if t.done else ft.TextDecoration.NONE
                ),
            ),
            check_color=theme.ON_PRIMARY,
            fill_color=theme.PRIMARY,
            on_change=lambda e, item_id=t.id: self._toggle(item_id, bool(e.control.value)),
        )
        delete = ft.IconButton(
            icon=ft.Icons.CLOSE,
            icon_size=18,
            icon_color=theme.TEXT_DIM,
            on_click=lambda e, item_id=t.id: self._delete(item_id),
        )
        return ft.Row([cb, ft.Container(expand=True), delete],
                      spacing=4, vertical_alignment=ft.CrossAxisAlignment.CENTER)

    def _toggle(self, item_id: str, done: bool) -> None:
        if not self._tasks:
            return

        async def _do() -> None:
            try:
                await self._tasks.set_done(item_id, done)
            except Exception as e:
                log.warning("grocery: toggle failed type=%s", type(e).__name__)
            await self.refresh()

        self._run_async(_do)

    def _delete(self, item_id: str) -> None:
        if not self._tasks:
            return

        async def _do() -> None:
            try:
                await self._tasks.delete(item_id)
            except Exception as e:
                log.warning("grocery: delete failed type=%s", type(e).__name__)
            await self.refresh()

        self._run_async(_do)

    def _on_submit(self, _e: ft.ControlEvent) -> None:
        if not self._tasks:
            return
        text = (self._input.value or "").strip()
        if not text:
            return

        async def _do() -> None:
            try:
                await self._tasks.add(text)
            except ValueError:
                self._input.error_text = "Invalid text"
                safe_update(self)
                return
            self._input.value = ""
            self._input.error_text = None
            await self.refresh()
            # ``focus`` is async in Flet 0.85; await it here so the
            # coroutine actually runs (previously it was created and
            # discarded, producing a "never awaited" warning).
            await self._input.focus()

        self._run_async(_do)
