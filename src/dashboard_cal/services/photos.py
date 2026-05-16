"""Local-folder photo cycler for the background slideshow.

We scan the configured folder for image files and hand them out in randomized
or sequential order. The path-traversal-prevention rule is applied: every
candidate file must resolve to a child of the configured folder before we'll
hand it to the UI.
"""

from __future__ import annotations

import logging
import random
from pathlib import Path

log = logging.getLogger(__name__)

ALLOWED_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}


class PhotoCycler:
    """Stateful iterator over images in a folder."""

    def __init__(self, folder: Path, shuffle: bool = True) -> None:
        self._folder = folder.resolve()
        self._shuffle = shuffle
        self._files: list[Path] = []
        self._idx = 0
        self.refresh()

    def refresh(self) -> None:
        if not self._folder.is_dir():
            log.warning("photos: folder does not exist")
            self._files = []
            return
        files: list[Path] = []
        for p in self._folder.iterdir():
            if not p.is_file():
                continue
            if p.suffix.lower() not in ALLOWED_SUFFIXES:
                continue
            # Path traversal guard: resolve and ensure it's under the configured folder.
            # If the user's folder contains a symlink pointing elsewhere, skip it.
            try:
                resolved = p.resolve()
            except OSError:
                continue
            try:
                resolved.relative_to(self._folder)
            except ValueError:
                log.warning("photos: skipping out-of-folder file")
                continue
            files.append(resolved)
        if self._shuffle:
            random.shuffle(files)
        else:
            files.sort()
        self._files = files
        self._idx = 0
        log.info("photos: refreshed count=%d", len(self._files))

    def next(self) -> Path | None:
        if not self._files:
            return None
        path = self._files[self._idx]
        self._idx = (self._idx + 1) % len(self._files)
        if self._shuffle and self._idx == 0:
            random.shuffle(self._files)
        return path

    def has_photos(self) -> bool:
        return bool(self._files)
