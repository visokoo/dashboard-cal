"""TodoStore tests against a temp SQLite file."""

from __future__ import annotations

from pathlib import Path

import pytest

from dashboard_cal.services.todos import TodoStore


@pytest.fixture()
def store(tmp_path: Path) -> TodoStore:
    s = TodoStore(db_path=tmp_path / "test.db")
    yield s
    s.close()


def test_add_and_list(store: TodoStore) -> None:
    t = store.add("Buy milk")
    assert t.text == "Buy milk"
    assert t.done is False
    items = store.list()
    assert len(items) == 1
    assert items[0].id == t.id


def test_add_empty_rejected(store: TodoStore) -> None:
    with pytest.raises(ValueError):
        store.add("   ")


def test_add_too_long_rejected(store: TodoStore) -> None:
    with pytest.raises(ValueError):
        store.add("x" * 5000)


def test_set_done(store: TodoStore) -> None:
    t = store.add("Pay rent")
    store.set_done(t.id, True)
    items = store.list()
    assert items[0].done is True
    assert items[0].completed_at is not None


def test_delete(store: TodoStore) -> None:
    t = store.add("Email Sarah")
    store.delete(t.id)
    assert store.list() == []


def test_clear_completed(store: TodoStore) -> None:
    a = store.add("a")
    b = store.add("b")
    store.set_done(a.id, True)
    n = store.clear_completed()
    assert n == 1
    remaining = store.list()
    assert len(remaining) == 1
    assert remaining[0].id == b.id


def test_sort_order_done_last(store: TodoStore) -> None:
    a = store.add("a")
    b = store.add("b")
    store.set_done(a.id, True)
    items = store.list()
    # Undone first (most recent first), then done.
    assert items[0].id == b.id
    assert items[1].id == a.id
