# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""AutoCAD command aliases — the muscle-memory table.

The defaults replicate the stock ``acad.pgp`` entries for the commands in
IngeCAD's scope: an AutoCAD user types ``M`` + Enter and gets MOVE without
reading any documentation. Users can override or extend them with their own
PGP file (``~/.config/IngeCAD/acad.pgp``), same syntax as AutoCAD's:

    ; comment
    CO,       *COPY
"""
from __future__ import annotations

from pathlib import Path

# Stock acad.pgp aliases for the product scope (v0.1).
DEFAULT_ALIASES: dict[str, str] = {
    "L": "LINE",
    "C": "CIRCLE",
    "A": "ARC",
    "PL": "PLINE",
    "REC": "RECTANG",
    "POL": "POLYGON",
    "EL": "ELLIPSE",
    "PO": "POINT",
    "DT": "TEXT",
    "T": "MTEXT",
    "MT": "MTEXT",
    "E": "ERASE",
    "M": "MOVE",
    "CO": "COPY",
    "CP": "COPY",
    "RO": "ROTATE",
    "O": "OFFSET",
    "TR": "TRIM",
    "EX": "EXTEND",
    "MI": "MIRROR",
    "SC": "SCALE",
    "B": "BLOCK",
    "ATT": "ATTDEF",
    "-ATT": "-ATTDEF",
    "ATE": "ATTEDIT",
    "-ATE": "-ATTEDIT",
    "ATTE": "ATTEDIT",
    "BE": "BEDIT",
    "I": "INSERT",
    "H": "HATCH",
    "-H": "-HATCH",
    "LA": "LAYER",
    "-LA": "-LAYER",
    "LO": "LAYOUT",
    "MV": "MVIEW",
    "MS": "MSPACE",
    "PS": "PSPACE",
    "DS": "DSETTINGS",
    "SE": "DSETTINGS",
    "OS": "OSNAP",
    "ST": "STYLE",
    "D": "DIMSTYLE",
    "DDIM": "DIMSTYLE",
    "DLI": "DIMLINEAR",
    "DIMLIN": "DIMLINEAR",
    "DAL": "DIMALIGNED",
    "DIMALI": "DIMALIGNED",
    "DRA": "DIMRADIUS",
    "DDI": "DIMDIAMETER",
    "DAN": "DIMANGULAR",
    "DIMANG": "DIMANGULAR",
    "DAR": "DIMARC",
    "DOR": "DIMORDINATE",
    "DCE": "DIMCENTER",
    "DCO": "DIMCONTINUE",
    "DIMCONT": "DIMCONTINUE",
    "DBA": "DIMBASELINE",
    "DIMBASE": "DIMBASELINE",
    "DIMTED": "DIMTEDIT",
    "DJO": "DIMJOGGED",
    "JOG": "DIMJOGGED",
    "MLD": "MLEADER",
    "LE": "QLEADER",
    "LEAD": "LEADER",
    "Z": "ZOOM",
    "AP": "APPLOAD",
    "SCR": "SCRIPT",
    "P": "PAN",
    "DI": "DIST",
    "AA": "AREA",
    "DR": "DRAWORDER",
    "OP": "OPTIONS",
    "G": "GROUP",
    "QC": "QUICKCALC",
    "ISOLATE": "ISOLATEOBJECTS",
    "UNISOLATE": "UNISOLATEOBJECTS",

    "IAT": "IMAGEATTACH",
    "SPL": "SPLINE",
    "TB": "TABLE",
    "LI": "LIST",
    "LS": "LIST",
    "X": "EXPLODE",
    "F": "FILLET",
    "RE": "REGEN",
    "XL": "XLINE",
    "XA": "XATTACH",
    "XR": "XREF",
    "-XR": "-XREF",
    "DIV": "DIVIDE",
    "ME": "MEASURE",
    "PU": "PURGE",
    "W": "WBLOCK",
    "MA": "MATCHPROP",
    "HE": "HATCHEDIT",
    "UN": "UNITS",
    "-UN": "-UNITS",
    "DDUNITS": "UNITS",
    "LTS": "LTSCALE",
    "LT": "LINETYPE",
    "LTYPE": "LINETYPE",
    "-LT": "-LINETYPE",
    "-LTYPE": "-LINETYPE",
    "S": "STRETCH",
    "BR": "BREAK",
    "J": "JOIN",
    "CHA": "CHAMFER",
    "AR": "ARRAY",
    "-AR": "ARRAY",
    "-ARRAY": "ARRAY",       # the command-line ARRAY is what ours is
    # AutoCAD's own aliases: unknown, these fell to prefix completion and
    # ran something else -- R ran RAY, CH ran CHAMFER, PR a survey command
    "DDEDIT": "TEXTEDIT",
    "ED": "TEXTEDIT",
    "PR": "PROPERTIES",
    "CH": "PROPERTIES",
    "PROPS": "PROPERTIES",
    "MO": "PROPERTIES",
    "R": "REDRAW",
    "RA": "REDRAWALL",
    "LW": "LWEIGHT",
    "DTEXT": "TEXT",
    "PE": "PEDIT",
    "LEN": "LENGTHEN",
    "AL": "ALIGN",
    "BO": "BOUNDARY",
    "-BO": "-BOUNDARY",
    "DO": "DONUT",
}


def parse_pgp(text: str) -> dict[str, str]:
    """Parse AutoCAD PGP alias lines: ``ALIAS, *COMMAND``.

    Lines without the ``*`` marker (external command definitions) and
    comments (``;``) are ignored, like AutoCAD does for aliases.
    """
    aliases: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.split(";", 1)[0].strip()
        if not line or "," not in line:
            continue
        alias, _, command = line.partition(",")
        command = command.strip()
        if not command.startswith("*"):
            continue
        alias = alias.strip().upper()
        command = command[1:].strip().upper()
        if alias and command:
            aliases[alias] = command
    return aliases


def user_pgp_path() -> Path:
    from core.paths import user_config_dir

    return user_config_dir() / "acad.pgp"


def starter_pgp() -> str:
    """The file Tools > Customize > Edit Program Parameters creates when
    there is none yet: the syntax, and the stock aliases to edit."""
    lines = [
        "; IngeCAD - program parameters (acad.pgp), same syntax as AutoCAD's.",
        ";",
        ";   ALIAS,  *COMMAND",
        ";",
        "; COMMAND may be an English command name (MOVE) or a localized one",
        "; (DESPLAZA), so a Spanish AutoCAD acad.pgp works as it is. Lines",
        "; starting with ; are comments. Type REINIT after saving this file",
        "; to use the changes without restarting IngeCAD.",
        ";",
        "; The stock aliases:",
    ]
    width = max(len(alias) for alias in DEFAULT_ALIASES) + 1
    for alias, command in DEFAULT_ALIASES.items():
        lines.append(f"{alias + ',':<{width + 1}} *{command}")
    return "\n".join(lines) + "\n"


def load_aliases(pgp_path: Path | None = None) -> dict[str, str]:
    """Stock aliases, then the site's acad.pgp (core.site), then the user's
    -- each overriding the one before."""
    aliases = dict(DEFAULT_ALIASES)
    if pgp_path is None:
        # a classroom's or an office's acad.pgp, under the user's own
        from core import site

        shared = site.site_pgp()
        if shared is not None:
            try:
                aliases.update(parse_pgp(read_pgp(shared)))
            except OSError:
                pass
    path = pgp_path or user_pgp_path()
    try:
        aliases.update(parse_pgp(read_pgp(path)))
    except OSError:
        pass
    return aliases


def read_pgp(path: Path) -> str:
    """A PGP file's text. AutoCAD writes them in ANSI (cp1252); a file
    saved as UTF-8 is read as such, anything else as cp1252."""
    data = path.read_bytes()
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def resolve(token: str, aliases: dict[str, str]) -> str:
    """Alias or full command name -> canonical command name (uppercase)."""
    name = token.strip().upper()
    return aliases.get(name, name)
