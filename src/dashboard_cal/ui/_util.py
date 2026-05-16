"""Tiny shared UI helpers."""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


def safe_update(control: Any) -> None:
    """Call ``control.update()`` and swallow the "not yet mounted" exception.

    In Flet 1.0 (0.70+), calling ``update()`` on a control that hasn't been
    added to a page yet raises ``Control must be added to the page first``.
    That can happen when a control's own ``__init__`` or constructor-time
    helper rebuilds child controls and tries to push the change. We only
    want the update to happen when we're already mounted; otherwise the
    parent's first render will pick up the new state anyway.

    Any unexpected exception is logged (without payload) and then swallowed
    so it cannot crash the UI loop.
    """
    try:
        control.update()
    except Exception:  # noqa: BLE001 - intentional broad catch with logging
        # Don't log the exception text or the control state - both can contain
        # user/event data that the logging-security rule says we must not log.
        log.debug("safe_update: control not yet mounted; skipping")
