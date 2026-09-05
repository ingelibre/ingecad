# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""How far the mouse reaches, in logical pixels: the one place that knows.

Three apertures, each the half-side of a square around the cursor:

* ``SNAP_PX`` -- object snap looks this far for an endpoint, a midpoint...
* ``GRIP_PX`` -- a grip is grabbed within this distance.
* ``pickbox()`` -- object selection, AutoCAD's PICKBOX (Command Reference
  p. 2452): Options > Selection or the PICKBOX command, saved in the
  registry as the reference says. It drives the box the crosshair draws AND
  the aperture that picks -- the two used to be independent constants that
  happened to read 8, and the drawn box was half the size of what it caught.

Pixels become a distance of the current space in exactly one place as well,
``ToolController.px_to_space``: the view's scale takes pixels to the canvas,
and inside MSPACE the viewport's scale takes paper to model. A caller that
divides by the view scale on its own is a second answer -- the dimension
magnet did, and reached five times too little through a 1:5 viewport.
"""
from __future__ import annotations

from core.prefs import int_pref

SNAP_PX = 12.0
GRIP_PX = 7.0
PICKBOX_DEFAULT = 8
SETTING_PICKBOX = "selection/pickbox"


def pickbox() -> int:
    """The live PICKBOX, 1-50 pixels."""
    return int_pref(SETTING_PICKBOX, PICKBOX_DEFAULT, 1, 50)
