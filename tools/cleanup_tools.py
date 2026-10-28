# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Cleanup tools that need the mouse: OVERKILL and WBLOCK (#37).

The headless work is in :mod:`core.cleanup`; these classes only run
AutoCAD's prompt sequences over it. -PURGE has no mouse phase and lives as
a Prompt chain (``core.cleanup.purge_command``).
"""
from __future__ import annotations

from pathlib import Path

from core import actions, cleanup
from core.i18n import tr
from tools.base import Point, Tool


class OverkillTool(Tool):
    """OVERKILL: select objects, adjust the options, delete duplicates."""

    wants_selection = True

    def start(self) -> None:
        self.name = "OVERKILL"
        self._entities: list = []
        self._settings = cleanup.OverkillSettings()
        self._stage = "options"

    def selection_prompt(self) -> str:
        return tr("Select objects:")

    def on_selection(self, entities: list) -> None:
        if not entities:
            self.ctx.finish()
            return
        self._entities = list(entities)
        self.prompt(cleanup.OVERKILL_PROMPT)

    # -- prompts -------------------------------------------------------------
    def _ask_yes_no(self, source: str, attribute: str, current: bool) -> None:
        self._stage = ("yesno", source, attribute)
        self.prompt(source, current=tr("Yes") if current else tr("No"))

    def on_option(self, text: str) -> bool:
        stage = self._stage
        if isinstance(stage, tuple) and stage[0] == "yesno":
            _kind, source, attribute = stage
            key = self.option(text)
            if key not in ("Y", "N"):
                self.ctx.echo(tr("Invalid option keyword."))
                return True
            setattr(self._settings, attribute, key == "Y")
            self._stage = "options"
            self.prompt(cleanup.OVERKILL_PROMPT)
            return True
        if stage == "tolerance":
            try:
                value = float(text)
            except ValueError:
                self.ctx.echo(tr("Requires numeric distance."))
                return True
            if value < 0:
                self.ctx.echo(tr("Value must be positive."))
                return True
            self._settings.tolerance = value
            self._stage = "options"
            self.prompt(cleanup.OVERKILL_PROMPT)
            return True
        if stage == "ignore":
            key = self.option(text)
            if key is None or key == "":
                self.ctx.echo(tr("Invalid option keyword."))
                return True
            if key == "N":
                self._settings.ignore.clear()
            else:
                self._settings.ignore.symmetric_difference_update({key})
            self.ctx.echo(tr("Ignored properties: {names}",
                             names=", ".join(sorted(self._settings.ignore)) or tr("none")))
            self._stage = "options"
            self.prompt(cleanup.OVERKILL_PROMPT)
            return True
        key = self.option(text)
        s = self._settings
        if key == "I":
            self._stage = "ignore"
            self.prompt(cleanup.IGNORE_PROMPT)
        elif key == "T":
            self._stage = "tolerance"
            self.prompt("Enter tolerance <{value}>:", value=f"{s.tolerance:g}")
        elif key == "O":
            self._ask_yes_no("Optimize segments within polylines? [Yes/No] <{current}>:",
                             "optimize_plines", s.optimize_plines)
        elif key == "P":
            self._ask_yes_no("Combine co-linear objects that partially overlap? "
                             "[Yes/No] <{current}>:", "partial", s.partial)
        elif key == "E":
            self._ask_yes_no("Combine co-linear objects when aligned end to end? "
                             "[Yes/No] <{current}>:", "end_to_end", s.end_to_end)
        elif key == "A":
            self._ask_yes_no("Maintain associative objects? [Yes/No] <{current}>:",
                             "associative", s.associative)
        elif key == "D":
            self._run()
        else:
            self.ctx.echo(tr("Invalid option keyword."))
        return True

    def on_enter(self) -> None:
        stage = self._stage
        if stage == "options":
            self._run()
            return
        # Enter at a sub-prompt keeps the current value
        self._stage = "options"
        self.prompt(cleanup.OVERKILL_PROMPT)

    def _run(self) -> None:
        plan = cleanup.overkill_plan(self._entities, self._settings)
        command = cleanup.overkill_command(plan)
        if command is not None:
            self.ctx.execute(command)
        self.ctx.echo(tr("{dups} duplicate(s) deleted, {overlaps} overlapping "
                         "object(s) or segment(s) deleted",
                         dups=plan.duplicate_count, overlaps=plan.overlap_count))
        self.ctx.finish()


class WblockTool(Tool):
    """WBLOCK: write a block, a selection or the whole drawing to a file.

    -WBLOCK's order (acad_acr p. 2089): the output file, then the block
    name prompt; "define new drawing" goes on to a base point and a
    selection. What happens to the selected objects afterwards follows the
    Write Block dialog's choice (Retain / Convert to block / Delete), asked
    at the prompt with Retain as the default.
    """

    def start(self) -> None:
        self.name = "WBLOCK"
        self._path: Path | None = None
        self._base: Point = (0.0, 0.0)
        self._entities: list = []
        self._stage = "name"
        services = self.ctx.services
        ask = getattr(services, "ask_save_file", None)
        # AutoCAD's Write Block proposes "new block.dwg": a DWG, since
        # that is what the colleague's INSERT > Browse expects
        chosen = ask(tr("Write Block"), tr("new block") + ".dwg",
                     tr("DWG drawing (*.dwg);;DXF drawing (*.dxf)")) if ask else None
        if not chosen:
            self.ctx.echo(tr("*Cancel*"))
            self.ctx.finish()
            return
        self._path = Path(chosen)
        self.prompt(cleanup.WBLOCK_PROMPT)

    def on_cancel(self) -> None:
        # The file was named in a dialog before the prompts, so leaving now
        # must say that nothing reached it (Rafael's review 6: he took the
        # closed dialog for a saved block).
        if self._path is not None and self._stage in ("name", "base", "select"):
            self.ctx.echo(tr("*Cancel* -- nothing was written to {path}.",
                             path=str(self._path)))
        self.ctx.finish()

    def _document(self):
        return self.ctx.services.document if hasattr(self.ctx.services, "document") \
            else self.ctx.services.window.document

    def _write(self, **kwargs) -> bool:
        try:
            count = cleanup.write_block_file(self._document(), self._path, **kwargs)
        except Exception as exc:  # noqa: BLE001 - say why, do not crash
            self.ctx.echo(tr("Could not write {path}: {error}",
                             path=str(self._path), error=str(exc)))
            return False
        self.ctx.echo(tr("{count} object(s) written to {path}.",
                         count=count, path=str(self._path)))
        return True

    def on_option(self, text: str) -> bool:
        if self._stage == "name":
            token = text.strip()
            doc = self._document().doc
            if token == "*":
                self._write(whole=True)
                self.ctx.finish()
                return True
            if token == "=":
                token = self._path.stem
            if token in doc.blocks and not doc.blocks.get(token).is_any_layout:
                self._write(block_name=token)
                self.ctx.finish()
                return True
            self.ctx.echo(tr('Block "{name}" not found.', name=token))
            self.prompt(cleanup.WBLOCK_PROMPT)
            return True
        if self._stage == "after":
            key = self.option(text)
            if key not in ("R", "C", "D"):
                self.ctx.echo(tr("Invalid option keyword."))
                return True
            self._after(key)
            return True
        return False

    def on_enter(self) -> None:
        if self._stage == "name":
            self._stage = "base"
            self.prompt("Specify insertion base point:")
            return
        if self._stage == "after":
            self._after("R")
            return
        self.ctx.finish()

    def on_point(self, point: Point) -> None:
        if self._stage != "base":
            return
        self._base = point
        self._stage = "select"
        request = getattr(self.ctx.services, "request_selection", None)
        if request is None:
            self.ctx.finish()
            return
        request()

    def selection_prompt(self) -> str:
        return tr("Select objects:")

    def on_selection(self, entities: list) -> None:
        if not entities:
            self.ctx.echo(tr("Nothing selected."))
            self.ctx.finish()
            return
        self._entities = list(entities)
        if not self._write(entities=self._entities,
                           base_point=(self._base[0], self._base[1], 0.0)):
            self.ctx.finish()
            return
        self._stage = "after"
        self.prompt("Enter an option [Retain/Convert to block/Delete] <Retain>:")

    def _after(self, key: str) -> None:
        if key == "D":
            self.ctx.execute(actions.EraseCommand(self._entities))
        elif key == "C":
            self.ctx.execute(actions.create_block(
                self._path.stem, (self._base[0], self._base[1]), self._entities))
        self.ctx.finish()


CLEANUP_TOOL_CLASSES = {
    "OVERKILL": OverkillTool,
    "-OVERKILL": OverkillTool,
    "WBLOCK": WblockTool,
    "-WBLOCK": WblockTool,
}
