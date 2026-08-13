# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The engine behind QUICKCALC — "a full range of mathematical, scientific,
and geometric calculations... and converts units of measurement" (p. 1588).

Expressions are evaluated by walking Python's own parse tree and refusing
everything that is not arithmetic: no names but the constants and functions
listed here, no attributes, no calls to anything else, no imports. A
calculator that can be handed a drawing from a colleague must not be a way
to run code.
"""
from __future__ import annotations

import ast
import math
import operator

#: The scientific area: what a drafter actually reaches for.
FUNCTIONS = {
    "sin": lambda x: math.sin(math.radians(x)),
    "cos": lambda x: math.cos(math.radians(x)),
    "tan": lambda x: math.tan(math.radians(x)),
    "asin": lambda x: math.degrees(math.asin(x)),
    "acos": lambda x: math.degrees(math.acos(x)),
    "atan": lambda x: math.degrees(math.atan(x)),
    "sqrt": math.sqrt,
    "abs": abs,
    "round": round,
    "ln": math.log,
    "log": math.log10,
    "exp": math.exp,
    "floor": math.floor,
    "ceil": math.ceil,
    "r2d": math.degrees,
    "d2r": math.radians,
}

CONSTANTS = {"pi": math.pi, "e": math.e}

_BINARY = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: math.fmod,
    ast.FloorDiv: operator.floordiv,
}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}


class CalcError(ValueError):
    """The expression is not something this calculator will evaluate."""


def evaluate(expression: str, variables: dict | None = None) -> float:
    """Evaluate an arithmetic expression, or raise :class:`CalcError`."""
    text = (expression or "").strip()
    if not text:
        raise CalcError("empty")
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError as exc:
        raise CalcError(str(exc)) from exc
    return _eval(tree.body, variables or {})


def _eval(node, variables):
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return float(node.value)
        raise CalcError("only numbers")
    if isinstance(node, ast.BinOp):
        op = _BINARY.get(type(node.op))
        if op is None:
            raise CalcError("operator not allowed")
        try:
            return float(op(_eval(node.left, variables),
                            _eval(node.right, variables)))
        except ZeroDivisionError as exc:
            raise CalcError("division by zero") from exc
    if isinstance(node, ast.UnaryOp):
        op = _UNARY.get(type(node.op))
        if op is None:
            raise CalcError("operator not allowed")
        return float(op(_eval(node.operand, variables)))
    if isinstance(node, ast.Name):
        key = node.id
        if key in variables:
            return float(variables[key])
        if key in CONSTANTS:
            return CONSTANTS[key]
        raise CalcError(f"unknown name: {key}")
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.keywords:
            raise CalcError("call not allowed")
        fn = FUNCTIONS.get(node.func.id)
        if fn is None:
            raise CalcError(f"unknown function: {node.func.id}")
        try:
            return float(fn(*[_eval(a, variables) for a in node.args]))
        except CalcError:
            raise
        except Exception as exc:
            raise CalcError(str(exc)) from exc
    raise CalcError("not an arithmetic expression")


# -- units conversion ---------------------------------------------------------
#: "Units Type: select length, area, volume, and angular values from a list"
#: (p. 1589). Each entry maps to the base unit of its family.
UNITS = {
    "Length": {"Millimeters": 0.001, "Centimeters": 0.01, "Meters": 1.0,
               "Kilometers": 1000.0, "Inches": 0.0254, "Feet": 0.3048,
               "Yards": 0.9144, "Miles": 1609.344},
    "Area": {"Square millimeters": 1e-6, "Square centimeters": 1e-4,
             "Square meters": 1.0, "Hectares": 1e4,
             "Square kilometers": 1e6, "Square inches": 0.00064516,
             "Square feet": 0.09290304, "Acres": 4046.8564224},
    "Volume": {"Cubic millimeters": 1e-9, "Cubic centimeters": 1e-6,
               "Liters": 0.001, "Cubic meters": 1.0,
               "Cubic inches": 1.6387064e-5, "Cubic feet": 0.028316846592,
               "Gallons (US)": 0.003785411784},
    "Angular": {"Degrees": 1.0, "Radians": 57.29577951308232,
                "Gradians": 0.9},
}


def convert(value: float, family: str, source: str, target: str) -> float:
    table = UNITS[family]
    return float(value) * table[source] / table[target]
