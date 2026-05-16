"""Material Design 3 color tokens.

Centralizes color choices so the rest of the UI doesn't reach into
Flet's raw color constants except via these names.

The five teal hues below are the requested calendar palette, from darkest
to lightest:

    DEEP_TEAL   = #18363E  -- darkest, used as a near-black surface tint
    DARK_TEAL   = #2D5F6E  -- secondary surface
    PRIMARY_TEAL= #3E88A5  -- primary action colour (today circle, event pills)
    MID_TEAL    = #5F97AA  -- accents (dividers, gridlines)
    LIGHT_TEAL  = #93C4D1  -- lightest, used for highlight text/icons
"""

from __future__ import annotations

import flet as ft

# Raw palette
DEEP_TEAL = "#18363E"
DARK_TEAL = "#2D5F6E"
PRIMARY_TEAL = "#3E88A5"
MID_TEAL = "#5F97AA"
LIGHT_TEAL = "#93C4D1"

# Surface tokens are layered teals with opacity so the photo background stays
# readable underneath. Using ``with_opacity`` on a teal (instead of black)
# gives the calendar that signature dark-teal cast even with no photo behind.
SURFACE = ft.Colors.with_opacity(0.78, DEEP_TEAL)
SURFACE_HIGH = ft.Colors.with_opacity(0.88, DARK_TEAL)
SURFACE_LOW = ft.Colors.with_opacity(0.55, DEEP_TEAL)

PRIMARY = PRIMARY_TEAL
ON_PRIMARY = ft.Colors.WHITE

ACCENT = LIGHT_TEAL
ERROR = ft.Colors.RED_400

TEXT = ft.Colors.with_opacity(0.95, ft.Colors.WHITE)
TEXT_MUTED = ft.Colors.with_opacity(0.78, LIGHT_TEAL)
TEXT_DIM = ft.Colors.with_opacity(0.50, LIGHT_TEAL)

DIVIDER = ft.Colors.with_opacity(0.25, MID_TEAL)
GRIDLINE = ft.Colors.with_opacity(0.18, MID_TEAL)
TODAY_FILL = PRIMARY_TEAL
EVENT_BLOCK = MID_TEAL
EVENT_DOT = LIGHT_TEAL


def build_theme() -> ft.Theme:
    """Material 3 theme tuned for an always-on display over photo backgrounds."""
    return ft.Theme(
        color_scheme_seed=PRIMARY_TEAL,
        color_scheme=ft.ColorScheme(
            primary=PRIMARY_TEAL,
            on_primary=ON_PRIMARY,
            secondary=MID_TEAL,
            tertiary=LIGHT_TEAL,
            surface=ft.Colors.with_opacity(0.0, DEEP_TEAL),
        ),
        use_material3=True,
        font_family="Roboto",
    )


CARD_RADIUS = 16
CARD_PADDING = 16

# ----------------------------------------------------------------------
# Week-view time-grid sizing
# ----------------------------------------------------------------------
HOUR_HEIGHT = 56  # pixels per hour
TIME_GUTTER = 60  # left gutter width for the hour labels

# The week view only renders this hour window (inclusive start, exclusive
# end). Events outside the window are skipped or clipped (see
# ``ui.calendar_view._event_block``). Use ``GRID_START_HOUR=0`` and
# ``GRID_END_HOUR=24`` to restore a full 24-hour grid.
GRID_START_HOUR = 7
GRID_END_HOUR = 24
GRID_HOURS = GRID_END_HOUR - GRID_START_HOUR
GRID_TOTAL_HEIGHT = GRID_HOURS * HOUR_HEIGHT
