"""Photo background slideshow with a dimming scrim for readability."""

from __future__ import annotations

import asyncio
import logging

import flet as ft

from ..config import PhotosConfig
from ..services.photos import PhotoCycler
from ._util import safe_update

log = logging.getLogger(__name__)

# 1x1 transparent PNG, used as a placeholder when the photos folder is empty
# (Flet 0.25+ requires Image.src at construction time).
_BLANK_PNG = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "YAAAAAYAAjCB0C8AAAAASUVORK5CYII="
)


class Background(ft.Stack):
    """A two-image cross-fade slideshow plus a scrim layer.

    Notes on Flet 0.85 API choices below:
    - ``ft.BoxFit.COVER`` (replaces the older ``ft.ImageFit.COVER`` that no
      longer exists at the top level).
    - ``animate_opacity`` accepts an ``int`` shorthand interpreted as
      duration in milliseconds with a linear curve (per the ``AnimationValue``
      contract).
    - ``src`` must be supplied at construction time on ``ft.Image``.
    """

    def __init__(self, photos: PhotosConfig) -> None:
        self._cfg = photos
        self._cycler = PhotoCycler(photos.resolved_folder(), shuffle=photos.shuffle)

        # Pre-load the first photo (if any) so both Images have valid `src`
        # values at construction. The hidden image (img_b) starts at the same
        # source as img_a and is swapped on the first rotation tick.
        first = self._cycler.next()
        initial_src = str(first) if first else _BLANK_PNG

        self._img_a = ft.Image(
            src=initial_src,
            fit=ft.BoxFit.COVER,
            expand=True,
            opacity=1.0,
            animate_opacity=800,
            gapless_playback=True,
        )
        self._img_b = ft.Image(
            src=initial_src,
            fit=ft.BoxFit.COVER,
            expand=True,
            opacity=0.0,
            animate_opacity=800,
            gapless_playback=True,
        )

        # Solid fallback shown through the images if both have no usable src.
        self._fallback = ft.Container(
            bgcolor=ft.Colors.BLUE_GREY_900,
            expand=True,
        )
        self._scrim = ft.Container(
            bgcolor=ft.Colors.with_opacity(photos.dim_percent / 100.0, ft.Colors.BLACK),
            expand=True,
        )
        self._on_top = "a"

        super().__init__(
            controls=[self._fallback, self._img_a, self._img_b, self._scrim],
            expand=True,
        )

    def start(self, page: ft.Page) -> None:
        if self._cycler.has_photos():
            # Only spin up the rotation task when there's something to rotate.
            page.run_task(self._loop)

    async def _loop(self) -> None:
        await asyncio.sleep(self._cfg.rotation_seconds)
        while True:
            try:
                nxt = self._cycler.next()
                if nxt:
                    await self._swap(str(nxt))
            except Exception:
                log.exception("background: rotation iteration failed")
            await asyncio.sleep(self._cfg.rotation_seconds)

    async def _swap(self, src: str) -> None:
        # Preload the hidden image, then cross-fade.
        if self._on_top == "a":
            self._img_b.src = src
            self._img_b.opacity = 1.0
            self._img_a.opacity = 0.0
            self._on_top = "b"
        else:
            self._img_a.src = src
            self._img_a.opacity = 1.0
            self._img_b.opacity = 0.0
            self._on_top = "a"
        safe_update(self)
