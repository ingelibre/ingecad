# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Drawing units — how a length is written, exactly as AutoCAD writes it.

The document is the model here too: the settings live in the DXF header
($LUNITS/$LUPREC/$AUNITS/$AUPREC/$INSUNITS), which is where AutoCAD keeps
them, so they survive the round trip untouched. This module only reads them
and formats numbers; the UNITS dialog writes them.

Formats follow the AutoCAD UNITS command:

    Scientific     1.55E+01
    Decimal        15.50
    Engineering    1'-3.50"
    Architectural  1'-3 1/2"
    Fractional     15 1/2

For architectural and engineering, one drawing unit IS one inch — that is
AutoCAD's rule, not a choice of ours.
"""
from __future__ import annotations

from fractions import Fraction

# $LUNITS
SCIENTIFIC = 1
DECIMAL = 2
ENGINEERING = 3
ARCHITECTURAL = 4
FRACTIONAL = 5

LINEAR_NAMES = {
    SCIENTIFIC: "Scientific",
    DECIMAL: "Decimal",
    ENGINEERING: "Engineering",
    ARCHITECTURAL: "Architectural",
    FRACTIONAL: "Fractional",
}

# $AUNITS
DEG = 0
DEG_MIN_SEC = 1
GRADS = 2
RADIANS = 3
SURVEYOR = 4

ANGULAR_NAMES = {
    DEG: "Decimal Degrees",
    DEG_MIN_SEC: "Deg/Min/Sec",
    GRADS: "Grads",
    RADIANS: "Radians",
    SURVEYOR: "Surveyor's Units",
}

# $INSUNITS — the value AutoCAD stores for "Units to scale inserted content".
# Only the entries a 2D drafter meets are offered by the dialog; the rest are
# preserved if a file already carries them.
INSUNIT_NAMES = {
    0: "Unitless",
    1: "Inches",
    2: "Feet",
    3: "Miles",
    4: "Millimeters",
    5: "Centimeters",
    6: "Meters",
    7: "Kilometers",
    8: "Microinches",
    9: "Mils",
    10: "Yards",
    11: "Angstroms",
    12: "Nanometers",
    13: "Microns",
    14: "Decimeters",
    15: "Decameters",
    16: "Hectometers",
    17: "Gigameters",
    18: "Astronomical units",
    19: "Light years",
    20: "Parsecs",
}

# Abbreviation AutoCAD prints after an area/length in the listing commands.
INSUNIT_ABBREV = {
    1: "in", 2: "ft", 3: "mi", 4: "mm", 5: "cm", 6: "m", 7: "km",
    10: "yd", 14: "dm",
}

# What the header holds, with AutoCAD's own defaults for a fresh drawing.
DEFAULTS = {
    "$LUNITS": DECIMAL,
    "$LUPREC": 4,
    "$AUNITS": DEG,
    "$AUPREC": 0,
    "$INSUNITS": 4,      # millimetres, the acadiso.dwt default
}


class Units:
    """The five header variables, read once and used to format."""

    def __init__(self, lunits: int = DECIMAL, luprec: int = 4,
                 aunits: int = DEG, auprec: int = 0,
                 insunits: int = 4) -> None:
        self.lunits = int(lunits)
        self.luprec = max(0, min(8, int(luprec)))
        self.aunits = int(aunits)
        self.auprec = max(0, min(8, int(auprec)))
        self.insunits = int(insunits)

    # -- document plumbing ----------------------------------------------------
    @classmethod
    def from_doc(cls, doc) -> "Units":
        """Read the header of an ezdxf document (or anything header-like)."""
        def get(name, default):
            try:
                value = doc.header[name]
            except Exception:
                return default
            try:
                return int(value)
            except (TypeError, ValueError):
                return default

        return cls(
            lunits=get("$LUNITS", DEFAULTS["$LUNITS"]),
            luprec=get("$LUPREC", DEFAULTS["$LUPREC"]),
            aunits=get("$AUNITS", DEFAULTS["$AUNITS"]),
            auprec=get("$AUPREC", DEFAULTS["$AUPREC"]),
            insunits=get("$INSUNITS", DEFAULTS["$INSUNITS"]),
        )

    def to_doc(self, doc) -> None:
        doc.header["$LUNITS"] = self.lunits
        doc.header["$LUPREC"] = self.luprec
        doc.header["$AUNITS"] = self.aunits
        doc.header["$AUPREC"] = self.auprec
        doc.header["$INSUNITS"] = self.insunits

    @property
    def unit_name(self) -> str:
        return INSUNIT_NAMES.get(self.insunits, "Unitless")

    @property
    def abbrev(self) -> str:
        """"mm", "m"… or "" when the drawing declares no unit."""
        return INSUNIT_ABBREV.get(self.insunits, "")

    @property
    def imperial(self) -> bool:
        """Architectural and engineering formats measure in inches."""
        return self.lunits in (ARCHITECTURAL, ENGINEERING)

    # -- formatting -----------------------------------------------------------
    def length(self, value: float) -> str:
        return format_length(value, self.lunits, self.luprec)

    def angle(self, degrees: float) -> str:
        return format_angle(degrees, self.aunits, self.auprec)

    def area(self, value: float) -> str:
        return format_area(value, self.lunits, self.luprec)

    def point(self, x: float, y: float, z: float = 0.0) -> str:
        return ", ".join(self.length(v) for v in (x, y, z))


def _fraction(value: float, denominator: int) -> tuple[int, Fraction]:
    """Split into whole part and a reduced fraction rounded to 1/denominator."""
    whole = int(abs(value))
    rest = Fraction(round((abs(value) - whole) * denominator), denominator)
    if rest >= 1:                       # rounding pushed it over
        whole += 1
        rest -= 1
    return whole, rest


def _fraction_text(whole: int, rest: Fraction) -> str:
    if rest == 0:
        return str(whole)
    if whole == 0:
        return f"{rest.numerator}/{rest.denominator}"
    return f"{whole} {rest.numerator}/{rest.denominator}"


def format_length(value: float, lunits: int = DECIMAL, luprec: int = 4) -> str:
    """One length, in the drawing's linear format."""
    luprec = max(0, min(8, int(luprec)))
    sign = "-" if value < 0 else ""
    magnitude = abs(value)

    if lunits == SCIENTIFIC:
        return f"{value:.{luprec}E}"

    if lunits == DECIMAL:
        return f"{value:.{luprec}f}"

    if lunits == ENGINEERING:
        feet = int(magnitude // 12)
        inches = magnitude - feet * 12
        if round(inches, luprec) >= 12:     # rounding rolled a foot over
            feet += 1
            inches = 0.0
        return f'{sign}{feet}\'-{inches:.{luprec}f}"'

    # Architectural and fractional round to 1/2**luprec of a unit.
    denominator = 2 ** luprec if luprec else 1
    if lunits == ARCHITECTURAL:
        feet = int(magnitude // 12)
        inches = magnitude - feet * 12
        whole, rest = _fraction(inches, denominator)
        if whole >= 12:
            feet += 1
            whole -= 12
        return f'{sign}{feet}\'-{_fraction_text(whole, rest)}"'

    if lunits == FRACTIONAL:
        whole, rest = _fraction(magnitude, denominator)
        return f"{sign}{_fraction_text(whole, rest)}"

    return f"{value:.{luprec}f}"


def format_angle(degrees: float, aunits: int = DEG, auprec: int = 0) -> str:
    """One angle, in the drawing's angular format."""
    auprec = max(0, min(8, int(auprec)))

    if aunits == GRADS:
        return f"{degrees * 10.0 / 9.0:.{auprec}f}g"
    if aunits == RADIANS:
        import math
        return f"{math.radians(degrees):.{auprec}f}r"
    if aunits == DEG_MIN_SEC:
        sign = "-" if degrees < 0 else ""
        total = abs(degrees)
        d = int(total)
        minutes_full = (total - d) * 60.0
        m = int(minutes_full)
        s = (minutes_full - m) * 60.0
        if round(s, auprec) >= 60:
            s = 0.0
            m += 1
        if m >= 60:
            m = 0
            d += 1
        return f'{sign}{d}d{m}\'{s:.{auprec}f}"'
    if aunits == SURVEYOR:
        # N/S <angle> E/W, measured from the north-south axis.
        a = degrees % 360.0
        if abs(a) < 1e-9 or abs(a - 360.0) < 1e-9:
            return "E"
        if abs(a - 90.0) < 1e-9:
            return "N"
        if abs(a - 180.0) < 1e-9:
            return "W"
        if abs(a - 270.0) < 1e-9:
            return "S"
        # A bearing is measured from the north-south axis toward east or west,
        # and is always under 90 degrees (Drawing Units, p.2002).
        north = a < 180.0
        east = a < 90.0 or a > 270.0
        if a < 90.0:
            bearing = 90.0 - a          # NE
        elif a < 180.0:
            bearing = a - 90.0          # NW
        elif a < 270.0:
            bearing = 270.0 - a         # SW
        else:
            bearing = a - 270.0         # SE
        ns = "N" if north else "S"
        ew = "E" if east else "W"
        return f"{ns} {format_angle(bearing, DEG_MIN_SEC, auprec)} {ew}"
    return f"{degrees:.{auprec}f}"


def format_area(value: float, lunits: int = DECIMAL, luprec: int = 4) -> str:
    """An area, the way AutoCAD reports it.

    In architectural and engineering drawings a unit is an inch, so AutoCAD
    reports square inches and adds the square-foot equivalent; every other
    format is plain square units.
    """
    if lunits in (ARCHITECTURAL, ENGINEERING):
        return (f"{value:.2f} square in. "
                f"({value / 144.0:.{max(1, min(8, int(luprec)))}f} square ft.)")
    return f"{value:.{max(0, min(8, int(luprec)))}f}"


# -- command-line flows --------------------------------------------------------
#
# -UNITS walks the prompts of the AutoCAD Command Reference (p.2004) in the
# same order and with the same wording, so a keyboard-only user gets the flow
# they know. LTSCALE lives here too: it is the other header variable that
# governs how the drawing reads on paper.

_REPORT_FORMATS = [
    (SCIENTIFIC, "1. Scientific     1.55E+01"),
    (DECIMAL, "2. Decimal        15.50"),
    (ENGINEERING, "3. Engineering    1'-3.50\""),
    (ARCHITECTURAL, "4. Architectural  1'-3 1/2\""),
    (FRACTIONAL, "5. Fractional     15 1/2"),
]

_ANGLE_SYSTEMS = [
    (DEG, "1. Decimal degrees          45.0000"),
    (DEG_MIN_SEC, "2. Degrees/minutes/seconds  45d0'0\""),
    (GRADS, "3. Grads                    50.0000g"),
    (RADIANS, "4. Radians                  0.7854r"),
    (SURVEYOR, "5. Surveyor's units         N 45d0'0\" E"),
]

# Architectural and fractional precision is named by the denominator, which is
# 2**LUPREC (-UNITS, p.2005).
_DENOMINATORS = [1, 2, 4, 8, 16, 32, 64, 128, 256]


def units_command(current: "Units", echo, apply, angdir: int = 0,
                  angbase: float = 0.0, args=()):
    """-UNITS. Returns a Prompt chain; ``apply(units, angdir, angbase)`` commits.

    Every prompt takes the current value as its default, so pressing Enter
    through the whole sequence changes nothing — the AutoCAD behaviour.
    """
    from core.actions import Prompt
    from core.i18n import tr

    chosen = Units(current.lunits, current.luprec, current.aunits,
                   current.auprec, current.insunits)
    state = {"angdir": int(angdir), "angbase": float(angbase)}

    def ask_length():
        echo(tr("Report formats: (Examples)"))
        for _value, line in _REPORT_FORMATS:
            echo(line)
        return Prompt(
            tr("Enter choice, 1 to 5 <{current}>:", current=chosen.lunits),
            on_length)

    def on_length(text):
        text = text.strip()
        if text:
            try:
                choice = int(text)
            except ValueError:
                echo(tr("Requires an integer between 1 and 5."))
                return ask_length()
            if not 1 <= choice <= 5:
                echo(tr("Requires an integer between 1 and 5."))
                return ask_length()
            chosen.lunits = choice
        return ask_length_precision()

    def ask_length_precision():
        if chosen.lunits in (ARCHITECTURAL, FRACTIONAL):
            return Prompt(
                tr("Enter denominator of smallest fraction to display "
                   "(1, 2, 4, 8, 16, 32, 64, 128, or 256) <{current}>:",
                   current=2 ** chosen.luprec),
                on_denominator)
        return Prompt(
            tr("Enter number of digits to right of decimal point (0 to 8) "
               "<{current}>:", current=chosen.luprec),
            on_digits)

    def on_digits(text):
        text = text.strip()
        if text:
            try:
                digits = int(text)
            except ValueError:
                digits = -1
            if not 0 <= digits <= 8:
                echo(tr("Requires an integer between 0 and 8."))
                return ask_length_precision()
            chosen.luprec = digits
        return ask_angle()

    def on_denominator(text):
        text = text.strip()
        if text:
            try:
                denominator = int(text)
            except ValueError:
                denominator = 0
            if denominator not in _DENOMINATORS:
                echo(tr("Requires 1, 2, 4, 8, 16, 32, 64, 128, or 256."))
                return ask_length_precision()
            chosen.luprec = _DENOMINATORS.index(denominator)
        return ask_angle()

    def ask_angle():
        echo(tr("Systems of angle measure: (Examples)"))
        for _value, line in _ANGLE_SYSTEMS:
            echo(line)
        return Prompt(
            tr("Enter choice, 1 to 5 <{current}>:", current=chosen.aunits + 1),
            on_angle)

    def on_angle(text):
        text = text.strip()
        if text:
            try:
                choice = int(text)
            except ValueError:
                choice = 0
            if not 1 <= choice <= 5:
                echo(tr("Requires an integer between 1 and 5."))
                return ask_angle()
            chosen.aunits = choice - 1
        return Prompt(
            tr("Enter number of fractional places for display of angles "
               "(0 to 8) <{current}>:", current=chosen.auprec),
            on_angle_precision)

    def on_angle_precision(text):
        text = text.strip()
        if text:
            try:
                digits = int(text)
            except ValueError:
                digits = -1
            if not 0 <= digits <= 8:
                echo(tr("Requires an integer between 0 and 8."))
                return Prompt(
                    tr("Enter number of fractional places for display of "
                       "angles (0 to 8) <{current}>:", current=chosen.auprec),
                    on_angle_precision)
            chosen.auprec = digits
        return ask_direction()

    def ask_direction():
        echo(tr("Direction for angle 0:"))
        echo(tr("East   3 o'clock =   0"))
        echo(tr("North 12 o'clock =  90"))
        echo(tr("West   9 o'clock = 180"))
        echo(tr("South  6 o'clock = 270"))
        return Prompt(
            tr("Enter direction for angle 0 <{current}>:",
               current=f"{state['angbase']:g}"),
            on_direction)

    def on_direction(text):
        text = text.strip()
        if text:
            try:
                state["angbase"] = float(text)
            except ValueError:
                echo(tr("Requires an angle."))
                return ask_direction()
        return Prompt(
            tr("Measure angles clockwise? [Yes/No] <{current}>:",
               current=tr("Yes") if state["angdir"] else tr("No")),
            on_clockwise)

    def on_clockwise(text):
        token = text.strip().upper()
        if token:
            if token.startswith("Y"):
                state["angdir"] = 1
            elif token.startswith("N"):
                state["angdir"] = 0
            else:
                echo(tr("Requires Yes or No."))
                return Prompt(
                    tr("Measure angles clockwise? [Yes/No] <{current}>:",
                       current=tr("Yes") if state["angdir"] else tr("No")),
                    on_clockwise)
        apply(chosen, state["angdir"], state["angbase"])
        return None

    if args:
        return on_length(str(args[0]))
    return ask_length()


def ltscale_command(current: float, echo, apply, args=()):
    """LTSCALE — the global linetype scale. Changing it regenerates."""
    from core.actions import Prompt
    from core.i18n import tr

    def commit(text):
        text = text.strip()
        if not text:
            return None
        try:
            value = float(text)
        except ValueError:
            echo(tr("Requires a number."))
            return ask()
        if value <= 0:
            echo(tr("Value must be positive."))
            return ask()
        apply(value)
        return None

    def ask():
        return Prompt(
            tr("Enter new linetype scale factor <{current}>:",
               current=f"{current:g}"),
            commit)

    if args:
        return commit(str(args[0]))
    return ask()
