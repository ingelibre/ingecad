# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Leader tools: MLEADER, QLEADER, LEADER -- AutoCAD's prompts and options.

Reference: ``docs/reference/dim/autocad-leaders.md``. The geometry and the
entities are ``core.leaders``; these state machines only collect points,
options and text. Text comes from the in-place MTEXT editor when the GUI
offers one (``services.open_mtext_editor``), from typed lines otherwise --
which is also what keeps the tools testable headless.
"""
from __future__ import annotations

from core import leaders
from core.i18n import tr
from tools.base import Point, Tool

_NOT_HERE = "{option} is not available in IngeCAD; Mtext or None."


class _TextLines:
    """Typed annotation lines: "Enter first line…" then "Enter next line…"
    until an empty Enter."""

    def _lines_start(self, first_prompt: str) -> None:
        self._lines: list[str] = []
        self._typing = True
        self.prompt(first_prompt)

    def _lines_add(self, text: str) -> None:
        self._lines.append(text)
        self.prompt("Enter next line of annotation text:")

    def wants_raw_text(self) -> bool:
        return bool(getattr(self, "_typing", False))

    def _open_editor(self, anchor: Point, char_height: float, commit) -> bool:
        """The GUI's in-place editor at ``anchor``; False when headless."""
        opener = getattr(self.ctx.services, "open_mtext_editor", None)
        if opener is None:
            return False
        try:
            second = (anchor[0] + 40.0 * char_height, anchor[1] - 2.0 * char_height)
            opener(anchor, second, char_height, commit=commit)
        except TypeError:
            return False          # an opener without the commit hook
        return True

    def _text_height(self) -> float:
        document = getattr(self.ctx.services, "document", None)
        doc = getattr(document, "doc", None)
        if doc is None:
            window = getattr(self.ctx.services, "window", None)
            document = getattr(window, "document", None)
            doc = getattr(document, "doc", None)
        if doc is None:
            return 2.5
        return leaders.dimstyle_values(doc)[1]


class MLeaderTool(_TextLines, Tool):
    """MLEADER: arrowhead, landing, content (or the other orders), with the
    Options submenu the reference lists."""

    def _text_height(self) -> float:
        """MLEADER writes with its own style: the editor shows that height
        (it showed the dimension style's 0.04 and saved 4.0)."""
        window = getattr(self.ctx.services, "window", None)
        document = getattr(window, "document", None)
        doc = getattr(document, "doc", None)
        if doc is None:
            return super()._text_height()
        return leaders.mleader_text_height(doc)

    #: session-wide, like AutoCAD's: the Options stick until changed
    leader_type = "S"          # Straight / sPline / None
    landing_on = True
    content = "M"              # Mtext / Block / None
    maxpoints = 2

    def start(self) -> None:
        self.name = "MLEADER"
        self._points: list[Point] = []
        self._landing: Point | None = None
        self._text: str | None = None
        self._block: str | None = None
        self._order = "arrow"          # arrow | landing | content
        self._want_landing = False
        self._pending: str | None = None
        self._typing = False
        self._first_prompt()

    def _first_prompt(self) -> None:
        self.prompt("Specify leader arrowhead location or "
                    "[leader Landing first/Content first/Options] <Options>:")

    def _options_prompt(self) -> None:
        self._pending = "options"
        self.prompt("Enter an option [Leader type/leader lAnding/Content type/"
                    "Maxpoints/First angle/Second angle/eXit options] "
                    "<eXit options>:")

    # -- points --------------------------------------------------------------
    def on_point(self, point: Point) -> None:
        if self._pending is not None or self._typing:
            return
        cls = type(self)
        if self._want_landing:
            self._want_landing = False
            self._landing = point
            self._content_then_build()
            return
        if self._order == "landing" and self._landing is None:
            self._landing = point
            self.last_point = point
            self.prompt("Specify leader arrowhead location:")
            return
        if self._order == "content" and self._landing is None:
            # the content goes here; the landing ends at it
            self._landing = point
            self.last_point = point
            self._content_first()
            return
        self._points.append(point)
        self.last_point = point
        if len(self._points) < cls.maxpoints - 1:
            self.prompt("Specify next point:")
            return
        if self._landing is None:
            self._want_landing = True
            self.prompt("Specify leader landing location:")
            return
        self._content_then_build()

    def _content_then_build(self) -> None:
        cls = type(self)
        if cls.content == "N" or self._text is not None or self._block is not None:
            self._build()
            return
        if cls.content == "B":
            name = self.ctx.ask_choice(
                tr("Enter block name:"), self._block_names(), "")
            if not name:
                self.ctx.finish()
                return
            self._block = name
            self._build()
            return
        anchor = self._landing or self._points[-1]

        def commit(text: str, extras: dict | None = None) -> None:
            self._text = text or ""
            self._build()

        if self._open_editor(anchor, self._text_height(), commit):
            self.ctx.finish()          # the editor commits when it closes
            return
        self._lines_start("Enter first line of annotation text <Mtext>:")

    def _block_names(self) -> list[str]:
        document = getattr(self.ctx.services, "document", None)
        doc = getattr(document, "doc", None)
        if doc is None:
            return []
        return sorted(b.name for b in doc.blocks if not b.name.startswith("*"))

    def _build(self) -> None:
        cls = type(self)
        if not self._points or self._landing is None:
            self.ctx.finish()
            return
        self.ctx.execute(leaders.add_mleader(
            self._points, self._landing, self._text or "",
            leader_type=cls.leader_type, landing_on=cls.landing_on,
            content=cls.content, block_name=self._block))
        self.ctx.finish()

    # -- options and typed text ---------------------------------------------
    def on_option(self, text: str) -> bool:
        cls = type(self)
        if self._typing:
            self._lines_add(text)
            return True
        pending, key = self._pending, self.option(text)
        if pending == "options":
            if key == "L":
                self._pending = "ltype"
                self.prompt("Select a leader type [Straight/sPline/None] <Straight>:")
            elif key == "A":
                self._pending = "landing"
                self.prompt("Use landing? [Yes/No] <Yes>:")
            elif key == "C":
                self._pending = "ctype"
                self.prompt("Select a content type [Block/Mtext/None] <Mtext>:")
            elif key == "M":
                self._pending = "maxpoints"
                self.prompt("Enter the maximum points for leader line <{n}>:",
                            n=cls.maxpoints)
            elif key in ("F", "S"):
                self.ctx.echo(tr("Angle constraints are not available in IngeCAD."))
                self._options_prompt()
            elif key == "X":
                self._pending = None
                self._first_prompt()
            else:
                self.ctx.echo(tr("Invalid option keyword."))
            return True
        if pending == "ltype":
            if key in ("S", "P", "N"):
                cls.leader_type = key
            self._options_prompt()
            return True
        if pending == "landing":
            if key in ("Y", "N"):
                cls.landing_on = key == "Y"
            self._options_prompt()
            return True
        if pending == "ctype":
            if key in ("B", "M", "N"):
                cls.content = key
            self._options_prompt()
            return True
        if pending == "maxpoints":
            try:
                n = int(text)
            except ValueError:
                self.ctx.echo(tr("Requires an integer value."))
                return True
            if n >= 2:
                cls.maxpoints = n
            self._options_prompt()
            return True
        if not self._points and self._landing is None:
            if key == "L":
                self._order = "landing"
                self.prompt("Specify leader landing location:")
                return True
            if key == "C":
                self._order = "content"
                self.prompt("Specify leader landing location:")
                return True
            if key == "O":
                self._options_prompt()
                return True
        return False

    def _content_first(self) -> None:
        def commit(text: str, extras: dict | None = None) -> None:
            self._text = text or ""
            self.prompt("Specify leader arrowhead location:")

        cls = type(self)
        if cls.content != "M":
            self._text = ""
            self.prompt("Specify leader arrowhead location:")
            return
        if self._open_editor(self._landing, self._text_height(), commit):
            self.prompt("Specify leader arrowhead location:")
            return
        self._lines_start("Enter first line of annotation text <Mtext>:")

    def on_enter(self) -> None:
        cls = type(self)
        if self._typing:
            self._typing = False
            self._text = "\\P".join(self._lines) if self._lines else ""
            if self._order == "content" and not self._points:
                self.prompt("Specify leader arrowhead location:")
            else:
                self._build()
            return
        if self._pending in ("ltype", "landing", "ctype", "maxpoints"):
            self._options_prompt()
            return
        if self._pending == "options":
            self._pending = None
            self._first_prompt()
            return
        if not self._points and self._landing is None:
            self._options_prompt()
            return
        if self._want_landing and self._points:
            # Enter at the landing prompt: "no text is associated with the
            # multileader object" -- the leader alone, no landing
            self._want_landing = False
            self.ctx.execute(leaders.add_mleader(
                self._points, self._points[-1], "",
                leader_type=cls.leader_type, landing_on=False, content="N"))
        self.ctx.finish()

    def preview_segments(self, cursor: Point):
        if self._pending is not None or self._typing:
            return []
        pts = list(self._points)
        if not pts:
            if self._landing is not None and self._order != "arrow":
                return [(self._landing, cursor)]
            return []
        segs = list(zip(pts, pts[1:] + [cursor]))
        if self._landing is not None and self._order != "arrow":
            segs = list(zip(pts, pts[1:])) + [(pts[-1], self._landing)]
        return segs


class QLeaderTool(_TextLines, Tool):
    """QLEADER: points (up to the Settings' number), text width, then the
    annotation lines or the in-place editor."""

    number_of_points = 3       # Leader Settings > Leader Line & Arrow

    def start(self) -> None:
        self.name = "QLEADER"
        self._points: list[Point] = []
        self._width = 0.0
        self._pending: str | None = None
        self._typing = False
        self.prompt("Specify first leader point, or [Settings] <Settings>:")

    def on_point(self, point: Point) -> None:
        if self._pending is not None:
            return
        self._points.append(point)
        self.last_point = point
        if len(self._points) < type(self).number_of_points:
            self.prompt("Specify next point:")
        else:
            self._ask_width()

    def _ask_width(self) -> None:
        self._pending = "width"
        self.prompt("Specify text width <0>:")

    def on_option(self, text: str) -> bool:
        if self._typing:
            self._lines_add(text)
            return True
        if self._pending == "settings":
            try:
                n = int(text)
            except ValueError:
                self.ctx.echo(tr("Requires an integer value."))
                return True
            if n >= 2:
                type(self).number_of_points = n
            self._pending = None
            self.prompt("Specify first leader point, or [Settings] <Settings>:")
            return True
        if self._pending == "width":
            try:
                self._width = max(0.0, float(text))
            except ValueError:
                self.ctx.echo(tr("Requires a numeric value."))
                return True
            self._pending = None
            self._lines_start("Enter first line of annotation text <Mtext>:")
            return True
        if not self._points and self.option(text) == "S":
            self._settings()
            return True
        return False

    def _settings(self) -> None:
        # The Leader Settings dialog, reduced to what this tool uses.
        self._pending = "settings"
        self.prompt("Enter number of leader points <{n}>:",
                    n=type(self).number_of_points)

    def on_enter(self) -> None:
        if self._typing:
            self._typing = False
            if self._lines:
                self._finish_with(self._lines)
                return
            # Enter with no text: the In-Place Text Editor
            anchor = self._points[-1]

            def commit(text: str, extras: dict | None = None) -> None:
                self._finish_with(text.split("\\P") if text else [])

            if self._open_editor(anchor, self._text_height(), commit):
                self.ctx.finish()
                return
            content = self.ctx.ask_text(tr("Enter text:"), "")
            self._finish_with(content.split("\\P") if content else [])
            return
        if self._pending == "width":
            self._pending = None
            self._lines_start("Enter first line of annotation text <Mtext>:")
            return
        if self._pending == "settings":
            self._pending = None
            self.prompt("Specify first leader point, or [Settings] <Settings>:")
            return
        if not self._points:
            self._settings()
            return
        if len(self._points) >= 2:
            self._ask_width()
            return
        self.ctx.finish()

    def _finish_with(self, lines: list[str]) -> None:
        if len(self._points) >= 2:
            self.ctx.execute(leaders.add_leader(
                self._points, lines or None, text_width=self._width))
        self.ctx.finish()

    def preview_segments(self, cursor: Point):
        pts = list(self._points)
        if not pts or self._pending is not None:
            return []
        return list(zip(pts, pts[1:] + [cursor]))


class LeaderTool(_TextLines, Tool):
    """LEADER: points, then Annotation/Format/Undo."""

    def start(self) -> None:
        self.name = "LEADER"
        self._points: list[Point] = []
        self._arrow = True
        self._spline = False
        self._pending: str | None = None
        self._typing = False
        self.prompt("Specify leader start point:")

    def _next_prompt(self) -> None:
        if len(self._points) < 2:
            self.prompt("Specify next point:")
        else:
            self.prompt("Specify next point or [Annotation/Format/Undo] "
                        "<Annotation>:")

    def on_point(self, point: Point) -> None:
        if self._pending is not None or self._typing:
            return
        self._points.append(point)
        self.last_point = point
        self._next_prompt()

    def on_option(self, text: str) -> bool:
        if self._typing:
            self._lines_add(text)
            return True
        key = self.option(text)
        if self._pending == "format":
            if key == "S":
                self._spline = True
            elif key == "ST":
                self._spline = False
            elif key == "A":
                self._arrow = True
            elif key == "N":
                self._arrow = False
            else:
                self.ctx.echo(tr("Invalid option keyword."))
                return True
            self._format_prompt()
            return True
        if self._pending == "annotation":
            if key == "M":
                self._pending = None
                self._mtext()
            elif key == "N":
                self._pending = None
                self._finish_with([])
            elif key in ("T", "C", "B"):
                self.ctx.echo(tr(_NOT_HERE, option={"T": "Tolerance", "C": "Copy",
                                                     "B": "Block"}[key]))
            else:
                self.ctx.echo(tr("Invalid option keyword."))
            return True
        if len(self._points) < 2:
            return False
        if key == "A":
            self._annotation()
            return True
        if key == "F":
            self._format_prompt()
            return True
        if key == "U":
            self._points.pop()
            self._next_prompt()
            return True
        return False

    def _format_prompt(self) -> None:
        self._pending = "format"
        self.prompt("Enter leader format option [Spline/STraight/Arrow/None] <Exit>:")

    def _annotation(self) -> None:
        self._lines_start("Enter first line of annotation text or <options>:")

    def _mtext(self) -> None:
        anchor = self._points[-1]

        def commit(text: str, extras: dict | None = None) -> None:
            self._finish_with(text.split("\\P") if text else [])

        if self._open_editor(anchor, self._text_height(), commit):
            self.ctx.finish()
            return
        content = self.ctx.ask_text(tr("Enter text:"), "")
        self._finish_with(content.split("\\P") if content else [])

    def on_enter(self) -> None:
        if self._typing:
            self._typing = False
            if self._lines:
                self._finish_with(self._lines)
            else:
                self._pending = "annotation"
                self.prompt("Enter an annotation option "
                            "[Tolerance/Copy/Block/None/Mtext] <Mtext>:")
            return
        if self._pending == "format":
            self._pending = None
            self._next_prompt()
            return
        if self._pending == "annotation":
            self._pending = None
            self._mtext()
            return
        if len(self._points) >= 2:
            self._annotation()
            return
        self.ctx.finish()

    def _finish_with(self, lines: list[str]) -> None:
        if len(self._points) >= 2:
            self.ctx.execute(leaders.add_leader(
                self._points, lines or None, arrow=self._arrow,
                spline=self._spline))
        self.ctx.finish()

    def preview_segments(self, cursor: Point):
        pts = list(self._points)
        if not pts or self._pending is not None or self._typing:
            return []
        return list(zip(pts, pts[1:] + [cursor]))


LEADER_TOOL_CLASSES = {
    "MLEADER": MLeaderTool,
    "QLEADER": QLeaderTool,
    "LEADER": LeaderTool,
}
