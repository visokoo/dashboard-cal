"""Tiny shared UI helpers."""

from __future__ import annotations

import logging
import os
import platform
import subprocess
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


def show_touch_keyboard() -> None:
    """Best-effort: surface the Windows on-screen touch keyboard.

    On Surface tablets the system normally pops the touch keyboard whenever
    a native text input gains focus. Flutter (which Flet renders through)
    does not always trigger that detection on Windows desktop builds, so we
    explicitly launch ``TabTip.exe`` -- Microsoft's touch keyboard binary,
    shipped with every Win10/Win11 install.

    Safe on non-Windows OSes (no-op). The subprocess is invoked with a
    static, pre-resolved file path and ``shell=False`` -- no user input is
    passed to the OS, so there's no command-injection surface.
    """
    if platform.system() != "Windows":
        return
    base = os.environ.get("CommonProgramFiles", r"C:\Program Files\Common Files")
    tabtip = os.path.join(base, "microsoft shared", "ink", "TabTip.exe")
    if not os.path.isfile(tabtip):
        return
    try:
        # ``shell=False`` + static absolute path: no shell parsing, no
        # injection vector. ``Popen`` returns immediately; we don't wait.
        subprocess.Popen([tabtip], shell=False)
    except OSError:
        # Best-effort: if TabTip isn't launchable (rare), the user can
        # still use a physical keyboard. Don't crash the UI.
        log.debug("touch keyboard: TabTip.exe failed to launch")
