"""Google Tasks adapter for the grocery list.

Picks (or creates) a task list with a configurable name and exposes CRUD-ish
operations to the UI. We don't store task data locally; everything round-trips
through Google so the user's phone/Gmail Tasks stays in sync.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

log = logging.getLogger(__name__)

MAX_TITLE_LEN = 500


@dataclass(frozen=True)
class GroceryItem:
    id: str
    title: str
    done: bool


class TasksService:
    def __init__(self, creds: Credentials, list_name: str) -> None:
        self._svc = build("tasks", "v1", credentials=creds, cache_discovery=False)
        self._list_name = list_name
        self._list_id: str | None = None

    async def ensure_list(self) -> str:
        if self._list_id:
            return self._list_id
        loop = asyncio.get_running_loop()
        try:
            self._list_id = await loop.run_in_executor(None, self._ensure_list_sync)
        except HttpError as e:
            log.warning("tasks: ensure_list failed status=%s", e.resp.status)
            raise RuntimeError("Could not access Google Tasks") from e
        return self._list_id

    def _ensure_list_sync(self) -> str:
        resp = self._svc.tasklists().list(maxResults=100).execute()
        for tl in resp.get("items", []):
            if tl.get("title") == self._list_name:
                return tl["id"]
        created = self._svc.tasklists().insert(body={"title": self._list_name}).execute()
        log.info("tasks: created list")
        return created["id"]

    async def list_items(self) -> list[GroceryItem]:
        list_id = await self.ensure_list()
        loop = asyncio.get_running_loop()
        try:
            raw = await loop.run_in_executor(None, self._list_sync, list_id)
        except HttpError as e:
            log.warning("tasks: list failed status=%s", e.resp.status)
            return []
        out = []
        for t in raw:
            if t.get("deleted"):
                continue
            out.append(
                GroceryItem(
                    id=str(t.get("id", "")),
                    title=str(t.get("title", "")).strip() or "(empty)",
                    done=t.get("status") == "completed",
                )
            )
        # Sort: undone first (by position), then done.
        out.sort(key=lambda i: (i.done, i.title.lower()))
        log.info("tasks: fetched count=%d", len(out))
        return out

    def _list_sync(self, list_id: str) -> list[dict]:
        items: list[dict] = []
        page_token: str | None = None
        while True:
            resp = (
                self._svc.tasks()
                .list(tasklist=list_id, showCompleted=True, showHidden=True, pageToken=page_token)
                .execute()
            )
            items.extend(resp.get("items", []))
            page_token = resp.get("nextPageToken")
            if not page_token:
                return items

    async def add(self, title: str) -> GroceryItem:
        title = (title or "").strip()
        if not title:
            raise ValueError("grocery item is empty")
        if len(title) > MAX_TITLE_LEN:
            raise ValueError(f"grocery item exceeds {MAX_TITLE_LEN} chars")
        list_id = await self.ensure_list()
        loop = asyncio.get_running_loop()
        created = await loop.run_in_executor(
            None,
            lambda: self._svc.tasks().insert(tasklist=list_id, body={"title": title}).execute(),
        )
        log.info("tasks: added len=%d", len(title))
        return GroceryItem(id=str(created["id"]), title=title, done=False)

    async def set_done(self, item_id: str, done: bool) -> None:
        list_id = await self.ensure_list()
        loop = asyncio.get_running_loop()
        body = {"id": item_id, "status": "completed" if done else "needsAction"}
        await loop.run_in_executor(
            None,
            lambda: self._svc.tasks().patch(tasklist=list_id, task=item_id, body=body).execute(),
        )
        log.info("tasks: set_done done=%s", done)

    async def delete(self, item_id: str) -> None:
        list_id = await self.ensure_list()
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            lambda: self._svc.tasks().delete(tasklist=list_id, task=item_id).execute(),
        )
        log.info("tasks: deleted")
