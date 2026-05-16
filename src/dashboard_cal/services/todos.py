"""Local todo list persisted to SQLite.

Schema:
    CREATE TABLE todos (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        text        TEXT NOT NULL,
        done        INTEGER NOT NULL DEFAULT 0,
        created_at  TEXT NOT NULL,
        completed_at TEXT
    );

All queries are parameterized (secure-sql rule).
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from platformdirs import user_data_path

log = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS todos (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    text        TEXT NOT NULL,
    done        INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    completed_at TEXT
);
"""

MAX_TEXT_LEN = 500


@dataclass(frozen=True)
class Todo:
    id: int
    text: str
    done: bool
    created_at: datetime
    completed_at: datetime | None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _row_to_todo(row: sqlite3.Row) -> Todo:
    return Todo(
        id=row["id"],
        text=row["text"],
        done=bool(row["done"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        completed_at=datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None,
    )


class TodoStore:
    """SQLite-backed todo store. Thread-safe enough for a single Flet app."""

    def __init__(self, db_path: Path | None = None) -> None:
        if db_path is None:
            db_path = user_data_path("dashboard-cal", appauthor=False, ensure_exists=True) / "app.db"
        self.db_path = Path(db_path)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def list(self, *, include_done: bool = True) -> list[Todo]:
        sql = "SELECT * FROM todos"
        params: tuple = ()
        if not include_done:
            sql += " WHERE done = 0"
        sql += " ORDER BY done ASC, created_at DESC"
        cur = self._conn.execute(sql, params)
        return [_row_to_todo(r) for r in cur.fetchall()]

    def add(self, text: str) -> Todo:
        text = (text or "").strip()
        if not text:
            raise ValueError("todo text is empty")
        if len(text) > MAX_TEXT_LEN:
            raise ValueError(f"todo text exceeds {MAX_TEXT_LEN} chars")
        now = _now()
        cur = self._conn.execute(
            "INSERT INTO todos (text, done, created_at) VALUES (?, 0, ?)",
            (text, now),
        )
        self._conn.commit()
        log.info("todos: added id=%s len=%d", cur.lastrowid, len(text))
        return Todo(
            id=int(cur.lastrowid),
            text=text,
            done=False,
            created_at=datetime.fromisoformat(now),
            completed_at=None,
        )

    def set_done(self, todo_id: int, done: bool) -> None:
        if done:
            self._conn.execute(
                "UPDATE todos SET done = 1, completed_at = ? WHERE id = ?",
                (_now(), todo_id),
            )
        else:
            self._conn.execute(
                "UPDATE todos SET done = 0, completed_at = NULL WHERE id = ?",
                (todo_id,),
            )
        self._conn.commit()
        log.info("todos: set_done id=%s done=%s", todo_id, done)

    def delete(self, todo_id: int) -> None:
        self._conn.execute("DELETE FROM todos WHERE id = ?", (todo_id,))
        self._conn.commit()
        log.info("todos: deleted id=%s", todo_id)

    def clear_completed(self) -> int:
        cur = self._conn.execute("DELETE FROM todos WHERE done = 1")
        self._conn.commit()
        log.info("todos: cleared completed count=%s", cur.rowcount)
        return cur.rowcount
