# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""UNITS: the five linear formats, the five angular ones, and -UNITS.

The expected strings are the examples the AutoCAD Command Reference itself
prints in the -UNITS prompt (p.2004): 1.55E+01 / 15.50 / 1'-3.50" /
1'-3 1/2" / 15 1/2 for the same 15.5, and 45.0000 / 45d0'0" / 50.0000g /
0.7854r / N 45d0'0" E for the same 45 degrees. If our formatter and the
manual disagree, the test fails on the manual's side.
"""
from __future__ import annotations

import pytest

from core import units as u
from core.units import Units


# -- linear formats ------------------------------------------------------------

def test_the_five_report_formats_match_the_manual_examples():
    value = 15.5
    assert u.format_length(value, u.SCIENTIFIC, 2) == "1.55E+01"
    assert u.format_length(value, u.DECIMAL, 2) == "15.50"
    assert u.format_length(value, u.ENGINEERING, 2) == "1'-3.50\""
    assert u.format_length(value, u.ARCHITECTURAL, 4) == "1'-3 1/2\""
    assert u.format_length(value, u.FRACTIONAL, 4) == "15 1/2"


def test_decimal_precision_is_the_digit_count():
    assert u.format_length(2.0 / 3.0, u.DECIMAL, 0) == "1"
    assert u.format_length(2.0 / 3.0, u.DECIMAL, 4) == "0.6667"
    assert u.format_length(2.0 / 3.0, u.DECIMAL, 8) == "0.66666667"


def test_fractional_precision_is_a_denominator_of_two():
    # LUPREC 3 means eighths; 0.1 rounds to 1/8, and 0.5 stays 1/2 reduced.
    assert u.format_length(0.1, u.FRACTIONAL, 3) == "1/8"
    assert u.format_length(0.5, u.FRACTIONAL, 3) == "1/2"
    assert u.format_length(2.0, u.FRACTIONAL, 3) == "2"


def test_a_rounding_that_completes_a_unit_carries():
    # 11.999 inches at 1/2" precision is a foot, not 0'-12".
    assert u.format_length(11.999, u.ARCHITECTURAL, 1) == "1'-0\""
    assert u.format_length(11.999, u.ENGINEERING, 2) == "1'-0.00\""


def test_negative_lengths_keep_their_sign():
    assert u.format_length(-15.5, u.FRACTIONAL, 4) == "-15 1/2"
    assert u.format_length(-15.5, u.ARCHITECTURAL, 4) == "-1'-3 1/2\""
    assert u.format_length(-15.5, u.DECIMAL, 2) == "-15.50"


# -- angular formats -----------------------------------------------------------

def test_the_five_angle_systems_match_the_manual_examples():
    assert u.format_angle(45.0, u.DEG, 4) == "45.0000"
    assert u.format_angle(45.0, u.DEG_MIN_SEC, 0) == "45d0'0\""
    assert u.format_angle(45.0, u.GRADS, 4) == "50.0000g"
    assert u.format_angle(45.0, u.RADIANS, 4) == "0.7854r"
    assert u.format_angle(45.0, u.SURVEYOR, 0) == "N 45d0'0\" E"


def test_surveyor_units_name_the_quadrant():
    assert u.format_angle(0.0, u.SURVEYOR, 0) == "E"
    assert u.format_angle(90.0, u.SURVEYOR, 0) == "N"
    assert u.format_angle(180.0, u.SURVEYOR, 0) == "W"
    assert u.format_angle(270.0, u.SURVEYOR, 0) == "S"
    assert u.format_angle(135.0, u.SURVEYOR, 0) == "N 45d0'0\" W"
    assert u.format_angle(225.0, u.SURVEYOR, 0) == "S 45d0'0\" W"
    assert u.format_angle(315.0, u.SURVEYOR, 0) == "S 45d0'0\" E"


def test_seconds_that_round_to_sixty_carry_into_minutes():
    assert u.format_angle(45.0 - 1e-9, u.DEG_MIN_SEC, 0) == "45d0'0\""


# -- header round trip ---------------------------------------------------------

def test_settings_live_in_the_dxf_header():
    from core.document import Document

    document = Document.new()
    Units(u.ARCHITECTURAL, 4, u.SURVEYOR, 2, 6).to_doc(document.doc)
    back = Units.from_doc(document.doc)
    assert (back.lunits, back.luprec) == (u.ARCHITECTURAL, 4)
    assert (back.aunits, back.auprec) == (u.SURVEYOR, 2)
    assert back.insunits == 6
    assert back.unit_name == "Meters"


def test_a_header_without_the_variables_falls_back_to_the_defaults():
    class Bare:
        header = {}

    back = Units.from_doc(Bare())
    assert back.lunits == u.DECIMAL and back.luprec == 4
    assert back.insunits == 4          # millimetres, the acadiso default


# -- -UNITS --------------------------------------------------------------------

class Runner:
    """Walks the Prompt chain the way the dispatcher does."""

    def __init__(self, current: Units, angdir: int = 0, angbase: float = 0.0):
        self.echoed: list[str] = []
        self.applied = None
        self.prompt = u.units_command(
            current, echo=self.echoed.append, apply=self._apply,
            angdir=angdir, angbase=angbase)

    def _apply(self, units, angdir, angbase):
        self.applied = (units, angdir, angbase)

    def send(self, text: str) -> None:
        assert self.prompt is not None, "the chain already finished"
        self.prompt = self.prompt.on_input(text)

    @property
    def text(self) -> str:
        return self.prompt.text if self.prompt else ""


def test_enter_through_the_whole_sequence_changes_nothing():
    current = Units(u.DECIMAL, 3, u.DEG_MIN_SEC, 2, 6)
    runner = Runner(current, angdir=1, angbase=90.0)
    for _ in range(5):                  # length, precision, angle, precision,
        runner.send("")                 # direction
    runner.send("")                     # clockwise
    units, angdir, angbase = runner.applied
    assert (units.lunits, units.luprec) == (u.DECIMAL, 3)
    assert (units.aunits, units.auprec) == (u.DEG_MIN_SEC, 2)
    assert units.insunits == 6          # untouched by -UNITS, as in AutoCAD
    assert (angdir, angbase) == (1, 90.0)


def test_architectural_asks_for_a_denominator_not_for_digits():
    runner = Runner(Units())
    assert "Enter choice, 1 to 5" in runner.text
    runner.send("4")                                    # Architectural
    assert "denominator of smallest fraction" in runner.text
    runner.send("16")
    for _ in range(4):
        runner.send("")
    units, _angdir, _angbase = runner.applied
    assert units.lunits == u.ARCHITECTURAL
    assert units.luprec == 4                            # 16 == 2**4
    assert units.length(15.5) == "1'-3 1/2\""


def test_decimal_asks_for_digits():
    runner = Runner(Units())
    runner.send("2")
    assert "digits to right of decimal point" in runner.text
    runner.send("2")
    for _ in range(4):
        runner.send("")
    units, _a, _b = runner.applied
    assert units.length(15.5) == "15.50"


def test_the_angle_choice_is_one_based_over_a_zero_based_variable():
    runner = Runner(Units())
    runner.send("")                     # keep decimal
    runner.send("")                     # keep precision
    assert "Systems of angle measure" in "\n".join(runner.echoed)
    runner.send("5")                    # Surveyor's units == $AUNITS 4
    runner.send("0")
    runner.send("")
    runner.send("")
    units, _a, _b = runner.applied
    assert units.aunits == u.SURVEYOR
    assert units.angle(45.0) == "N 45d0'0\" E"


def test_out_of_range_answers_reask_instead_of_committing():
    runner = Runner(Units())
    runner.send("9")
    assert runner.applied is None
    assert "between 1 and 5" in "\n".join(runner.echoed)
    assert "Enter choice, 1 to 5" in runner.text


def test_clockwise_answers_yes_or_no():
    runner = Runner(Units(), angdir=0)
    for _ in range(5):
        runner.send("")
    assert "clockwise" in runner.text.lower()
    runner.send("Y")
    _units, angdir, _angbase = runner.applied
    assert angdir == 1


def test_an_argument_on_the_command_line_starts_the_chain():
    runner = Runner(Units())
    assert runner.prompt is not None
    # -UNITS 4 lands straight on the denominator prompt.
    second = u.units_command(Units(), echo=lambda t: None,
                             apply=lambda *a: None, args=("4",))
    assert "denominator" in second.text


# -- LTSCALE -------------------------------------------------------------------

def test_ltscale_takes_a_factor_and_rejects_nonsense():
    applied = []
    echoed = []
    prompt = u.ltscale_command(1.0, echo=echoed.append, apply=applied.append)
    assert "linetype scale factor <1>" in prompt.text
    again = prompt.on_input("abc")
    assert applied == [] and "number" in echoed[0].lower()
    assert again is not None
    assert again.on_input("0") is not None      # not positive: ask again
    assert applied == []
    assert u.ltscale_command(1.0, echo=echoed.append,
                             apply=applied.append, args=("25",)) is None
    assert applied == [25.0]


def test_ltscale_enter_keeps_the_current_value():
    applied = []
    prompt = u.ltscale_command(3.0, echo=lambda t: None, apply=applied.append)
    assert prompt.on_input("") is None
    assert applied == []
