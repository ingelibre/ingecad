# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Interactive tool base: a UI-agnostic state machine fed with points.

A tool receives points (from snapped mouse clicks or typed coordinates —
it does not care which) and option keywords, asks for the next input via
prompts, and executes headless Commands. The GUI supplies a ToolContext
with callbacks; tests supply fakes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, ClassVar, Optional

Point = tuple[float, float]


@dataclass
class ToolContext:
    execute: Callable[[object], None]          # run an undoable Command
    prompt: Callable[[str], None]              # show prompt text
    echo: Callable[[str], None]                # log a message
    finish: Callable[[], None]                 # tool is done: deactivate
    # Ask the user for a text string (TEXT/MTEXT content) — a small dialog in
    # the GUI, a fake in tests. Returns None on cancel.
    ask_text: Callable[[str, str], Optional[str]] = lambda prompt, default="": None
    # Ask the user to choose one item from a list (INSERT block picker). GUI:
    # a dropdown dialog; tests: a fake. Returns None on cancel.
    ask_choice: Callable[[str, list, str], Optional[str]] = lambda prompt, items, default="": None
    # Open the hatch style picker with the current settings; returns the chosen
    # settings dict {pattern, scale, angle, color} or None on cancel.
    ask_hatch: Callable[[dict], Optional[dict]] = lambda settings: None
    # Undo the most recently executed Command (LINE's mid-command U erases
    # the segment for real, like AutoCAD — not just forgets the point).
    undo_last: Callable[[], None] = lambda: None
    # Editing services (selection, entity picking, edge geometry). The GUI
    # supplies the ToolController; tests supply a fake with the same duck
    # methods: pick_entity(point), edges_geometry(handles|None).
    services: object = None


@dataclass
class Tool:
    ctx: ToolContext
    name: str = "TOOL"
    last_point: Optional[Point] = None         # anchor for @rel / distances
    preview_points: list[Point] = field(default_factory=list)
    # Editing tools consume the current selection (noun-verb) or ask for
    # one ("Select objects:") before their point prompts. ClassVar on
    # purpose: a dataclass FIELD would make the generated __init__ reset
    # the subclass override back to False on every instance.
    wants_selection: ClassVar[bool] = False
    shift: ClassVar[bool] = False              # Shift held at last click
    # Tools whose clicks pick ENTITIES (trim targets, fillet lines) get raw
    # cursor points: AutoCAD suppresses osnap during object picking.
    entity_picker: ClassVar[bool] = False
    # Tools whose target phase also accepts window/crossing rectangles
    # (TRIM/EXTEND): a drag or empty-click window feeds many targets.
    accepts_target_windows: ClassVar[bool] = False

    #: Source (English) text of the prompt currently on screen. Every prompt a
    #: tool shows goes through :meth:`prompt`, so this is always the one the
    #: user is answering -- which is what lets :meth:`option` know which
    #: keywords are live. A prompt with no options clears them, so a "D" typed
    #: as a distance can never be eaten by an earlier prompt's Delete.
    _prompt_source: str = ""

    def prompt(self, source: str, **kwargs) -> None:
        """Show ``source`` translated, and remember it for :meth:`option`.

        Takes the **English source**, not a translated string: a prompt whose
        ``{placeholders}`` are already filled in cannot be mapped back to the
        catalog entry that lists its options.
        """
        from core.i18n import tr

        self._prompt_source = source
        self.ctx.prompt(tr(source, **kwargs))

    def option(self, text: str) -> str:
        """The English key ``text`` selects in the current prompt, or "".

        Returns what call sites have always compared against -- ``"D"``,
        ``"CE"`` -- so tools never learn that other languages exist. What
        arrives may be the English key, the English word, the translated word,
        or either behind AutoCAD's ``_`` global prefix.
        """
        from core.i18n import keywords

        return keywords.match(text, self._prompt_source) or ""

    def on_target_entities(self, entities: list, rect) -> None:
        """Targets captured by a window/crossing during the tool's pick phase."""

    def start(self) -> None: ...

    def selection_prompt(self) -> str:
        from core.i18n import tr

        return tr("Select objects (Enter when done):")

    def on_selection(self, entities: list) -> None: ...

    def on_point(self, point: Point) -> None: ...

    def on_option(self, text: str) -> bool:
        """A non-coordinate token from the prompt. True if consumed."""
        return False

    def wants_raw_text(self) -> bool:
        """True while the tool expects literal text (dimension text
        override, etc.): Space must insert a space, not execute."""
        return False

    def on_enter(self) -> None:
        """Enter on an empty prompt: finish where that is meaningful."""
        self.ctx.finish()

    def on_cancel(self) -> None:
        self.ctx.finish()

    def preview_segments(self, cursor: Point) -> list[tuple[Point, Point]]:
        """Rubber-band segments from committed points to the cursor."""
        return []

    def ghost_placement(self, cursor: Point):
        """(angle_degrees, factor) for a ghost that turns or grows.

        None — the default — means the ghost simply follows the cursor, the
        way a MOVE drag does. ROTATE and SCALE answer here so their preview
        shows the real result instead of a rubber-band line.
        """
        return None
