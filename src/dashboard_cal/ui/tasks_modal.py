"""Right-anchored slide-in modal for the tasks/todos panel.

Composes two layers inside a single ``Stack``:

1. A full-bleed scrim that darkens the underlying UI and forwards taps
   to the parent's ``on_dismiss`` handler (typically the same handler
   the X button uses).
2. The panel itself, sized to ``PANEL_WIDTH`` and pinned to the right edge.
   ``Container.animate_offset`` slides it on and off screen with a single
   ``ft.Offset(1.0, 0)`` (== 100 % of its own width to the right) toggle.

The modal is always present in the layer stack; ``visible=False`` while
closed keeps it from blocking pointer events on the calendar underneath.
"""

from __future__ import annotations

import flet as ft

from .. import theme
from ._util import safe_update

# Width of the slide-in panel. Wide enough for a comfortable two-column
# layout (Todos on top, Grocery below) but narrow enough that the calendar
# stays partially visible behind the scrim.
PANEL_WIDTH = 440

# Slide / fade animation duration in milliseconds.
ANIM_MS = 220


class TasksModal(ft.Stack):
    """Hosts an arbitrary ``content`` control as a right-anchored drawer."""

    def __init__(self, content: ft.Control, on_dismiss) -> None:
        self._open = False
        anim = ft.Animation(ANIM_MS, ft.AnimationCurve.EASE_OUT)

        # Scrim: full-bleed, transparent when closed, dim when open.
        # Taps go straight to the parent's dismiss handler so the X-button
        # and scrim-tap close paths share the same code path (including
        # any focus / keyboard cleanup the parent wants to run).
        self._scrim = ft.Container(
            left=0,
            right=0,
            top=0,
            bottom=0,
            bgcolor=ft.Colors.with_opacity(0.0, ft.Colors.BLACK),
            animate=anim,
            on_click=on_dismiss,
        )

        # The panel itself. The inner container holds the actual content; the
        # outer one owns the offset animation so the slide-in is smooth.
        # ``on_animation_end`` is how we know the close animation has fully
        # played -- at that point we can safely hide the whole Stack so the
        # scrim stops intercepting pointer events.
        self._panel = ft.Container(
            content=ft.Container(
                content=content,
                width=PANEL_WIDTH,
                padding=ft.Padding.symmetric(horizontal=20, vertical=24),
                bgcolor=theme.SURFACE_HIGH,
                border_radius=ft.BorderRadius.only(top_left=24, bottom_left=24),
            ),
            right=0,
            top=0,
            bottom=0,
            # ``ft.Offset(1.0, 0)`` shifts the container 100 % of its own
            # width to the right, parking it just off-screen.
            offset=ft.Offset(1.0, 0),
            animate_offset=anim,
            on_animation_end=self._on_anim_end,
        )

        super().__init__(
            controls=[self._scrim, self._panel],
            expand=True,
            # Hidden when closed so pointer events fall through to the
            # calendar. Toggled in ``open`` / ``close``.
            visible=False,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    @property
    def is_open(self) -> bool:
        return self._open

    def open(self) -> None:
        if self._open:
            return
        self._open = True
        self.visible = True
        self._scrim.bgcolor = ft.Colors.with_opacity(0.45, ft.Colors.BLACK)
        self._panel.offset = ft.Offset(0, 0)
        safe_update(self)

    def close(self) -> None:
        if not self._open:
            return
        self._open = False
        self._scrim.bgcolor = ft.Colors.with_opacity(0.0, ft.Colors.BLACK)
        self._panel.offset = ft.Offset(1.0, 0)
        # Stay ``visible=True`` for now so the slide-out animation can
        # play; ``_on_anim_end`` flips ``visible`` to False once it's done
        # so the scrim stops intercepting taps on the dashboard underneath.
        safe_update(self)

    def toggle(self) -> None:
        if self._open:
            self.close()
        else:
            self.open()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------
    def _on_anim_end(self, _e: ft.ControlEvent) -> None:
        """Called when the panel's offset animation finishes (open or close).

        For the close animation we need to fully un-mount the Stack from
        hit-testing -- otherwise the full-bleed scrim (transparent but
        still tap-eating because of its ``on_click`` handler) makes the
        rest of the dashboard unclickable.

        For the open animation this is a no-op (``_open`` is True).
        Re-entrancy is safe: if the user re-opens before the close anim
        finishes, ``_open`` will already be True by the time we fire here.
        """
        if not self._open and self.visible:
            self.visible = False
            safe_update(self)
