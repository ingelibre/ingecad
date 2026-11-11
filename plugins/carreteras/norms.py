# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Design standards as data: the minimum radii, the superelevation law, when a
curve needs a clothoid and how long, and how two curves may follow each
other -- one JSON file per standard in ``norms/`` beside this module, plus
any the user drops in ``<config>/IngeCAD/norms/`` (same name: the user's wins).

Nothing here is a number of its own: every value comes from a file that
names its source, and a file marked ``"verified": false`` says so in every
report. A category whose value is ``null`` is not checked for it.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

from core.i18n import tr

from . import geometry

HERE = Path(__file__).resolve().parent / "norms"


def _user_dir() -> Path | None:
    try:
        from core.paths import user_config_dir

        return user_config_dir() / "norms"
    except Exception:
        return None


@dataclass(frozen=True)
class Norm:
    id: str
    name: str
    verified: bool
    source: str
    note: str
    superelevation: dict
    clothoid: dict
    chaining: dict | None
    categories: dict
    arc_fraction_min: float | None = None

    @classmethod
    def from_dict(cls, d: dict) -> "Norm":
        return cls(str(d["id"]), str(d.get("name", d["id"])), bool(d.get("verified", False)),
                   str(d.get("source", "")), str(d.get("note", "")),
                   dict(d.get("superelevation") or {}), dict(d.get("clothoid") or {}),
                   d.get("chaining"), dict(d["categories"]), d.get("arc_fraction_min"))

    def category(self, name: str) -> dict:
        for key, value in self.categories.items():
            if key.lower() == name.strip().lower():
                return value
        raise KeyError(name)

    def category_name(self, name: str) -> str:
        for key in self.categories:
            if key.lower() == name.strip().lower():
                return key
        raise KeyError(name)


def available(extra_dirs=()) -> dict[str, Norm]:
    """Every standard found, by id (the user's folder after the bundled one)."""
    out: dict[str, Norm] = {}
    dirs = [HERE] + ([d for d in [_user_dir()] if d is not None]) + [Path(d) for d in extra_dirs]
    for folder in dirs:
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.json")):
            try:
                norm = Norm.from_dict(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError, KeyError, TypeError):
                continue
            out[norm.id] = norm
    return out


def find(name: str, extra_dirs=()) -> Norm:
    norms = available(extra_dirs)
    for key, norm in norms.items():
        if key.lower() == name.strip().lower():
            return norm
    raise KeyError(name)


# -- the rules ------------------------------------------------------------------------------

def superelevation(norm: Norm, cat: dict, radius: float) -> float | None:
    """The superelevation (%, towards the inside; negative: the crown kept)
    the standard gives a curve of ``radius``; None when it gives no law."""
    law = norm.superelevation
    rnd, rdm = cat.get("rnd"), cat.get("rdm")
    rm = cat.get("rm") if cat.get("rm") is not None else cat.get("superelevation_flat_below")
    crown = law.get("crown", -2.5)
    if rnd is not None and radius >= rnd:
        return crown
    span = cat.get("superelevation_range")
    if span:
        return float(span[1])
    if law.get("law") != "inverse_linear" or rdm is None or rm is None:
        return None
    dmin, dmax = float(law["min"]), float(law["max"])
    if radius >= rdm:
        return dmin
    if radius <= rm:
        return dmax
    return dmin + (dmax - dmin) * (1.0 / radius - 1.0 / rdm) / (1.0 / rm - 1.0 / rdm)


def clothoid_needed_below(norm: Norm, cat: dict) -> float | None:
    rule = norm.clothoid
    base = cat.get(rule.get("required_below", "rnd"))
    return None if base is None else float(base) * float(rule.get("factor", 1.0))


def clothoid_length(norm: Norm, cat: dict, radius: float, lanes: int = 2) -> float | None:
    """The clothoid length the standard recommends for a curve of ``radius``."""
    length = norm.clothoid.get("length") or {}
    formula = length.get("formula")
    if formula == "k_r04":
        k = length.get("k", {}).get(str(lanes)) or length.get("k", {}).get("2")
        if k is None:
            return None
        value = float(k) * radius ** 0.4
        cap = (length.get("cap") or {}).get(str(lanes))
        return min(value, float(cap)) if cap else value
    if formula == "max_2ldd_kr04":
        k = length.get("k", {}).get(str(lanes)) or length.get("k", {}).get("2")
        d = superelevation(norm, cat, radius)
        crown = norm.superelevation.get("crown", -2.5)
        dd = abs(d - crown) if d is not None else 0.0
        width = float(length.get("lane_width", 3.5)) * max(lanes, 2) / 2.0
        return max(2.0 * width * dd, float(k) * radius ** 0.4) if k else None
    if formula == "max_14dd_r9":
        d = superelevation(norm, cat, radius)
        crown = norm.superelevation.get("crown", -2.5)
        dd = (d - crown) if d is not None else 0.0
        return max(14.0 * dd, radius / 9.0)
    return None


def widening(cat: dict, radius: float) -> float | None:
    """The widening of each lane (m) the category gives a curve of
    ``radius``, or None when it gives none."""
    for rule in cat.get("widening") or []:
        if rule.get("min_radius", 0) <= radius <= rule.get("max_radius", math.inf):
            return float(rule["k"]) / radius
    return None


@dataclass
class Finding:
    level: str                      # "error", "warning" or "info"
    text: str


@dataclass
class Report:
    norm: Norm
    category: str
    findings: list[Finding] = field(default_factory=list)

    def add(self, level: str, text: str) -> None:
        self.findings.append(Finding(level, text))

    @property
    def errors(self) -> int:
        return sum(1 for f in self.findings if f.level == "error")

    @property
    def warnings(self) -> int:
        return sum(1 for f in self.findings if f.level == "warning")


def check(alignment: geometry.Alignment, norm: Norm, category: str, lanes: int = 2) -> Report:
    """Every curve of the axis against the standard: minimum radius,
    superelevation, clothoid presence and length, and the chaining of
    successive curves."""
    cat_name = norm.category_name(category)
    cat = norm.categories[cat_name]
    report = Report(norm, cat_name)
    groups = geometry.curve_groups(alignment)
    rm, rnd = cat.get("rm"), cat.get("rnd")
    needs = clothoid_needed_below(norm, cat)
    for g in groups:
        r = g.radius
        label = tr("C-{n}: R = {r:.2f} m", n=g.number, r=r)
        if rm is not None and r < rm - 1e-6:
            report.add("error", tr("{label}: below the minimum radius Rm = {rm:g} m.", label=label, rm=rm))
        d = superelevation(norm, cat, r)
        if d is None:
            if rnd is not None and r < rnd:
                report.add("info", tr("{label}: superelevated towards the inside (R < {rnd:g} m); "
                                      "see the standard for the value.", label=label, rnd=rnd))
        elif d < 0:
            report.add("info", tr("{label}: no superelevation, crown kept (R >= Rnd = {rnd:g} m).",
                                  label=label, rnd=rnd))
        else:
            report.add("info", tr("{label}: superelevation {d:.1f} % towards the inside.", label=label, d=d))
        ls_in = g.spiral_in.length if g.spiral_in else 0.0
        ls_out = g.spiral_out.length if g.spiral_out else 0.0
        wanted = clothoid_length(norm, cat, r, lanes)
        if needs is not None and r < needs:
            if ls_in <= 0 or ls_out <= 0:
                if wanted:
                    report.add("warning", tr("{label}: needs clothoids (R < {lim:g} m); recommended length "
                                             "{l:.1f} m (A = {a:.1f}).", label=label, lim=needs, l=wanted,
                                             a=math.sqrt(wanted * r)))
                else:
                    report.add("warning", tr("{label}: needs clothoids (R < {lim:g} m).", label=label, lim=needs))
            elif wanted and min(ls_in, ls_out) < wanted - 0.05:
                report.add("warning", tr("{label}: clothoid {ls:.1f} m, shorter than the {l:.1f} m "
                                         "recommended.", label=label, ls=min(ls_in, ls_out), l=wanted))
            elif wanted:
                report.add("info", tr("{label}: clothoids {ls:.1f} m (A = {a:.1f}), {l:.1f} m recommended.",
                                      label=label, ls=min(ls_in, ls_out), a=math.sqrt(min(ls_in, ls_out) * r),
                                      l=wanted))
        widen = widening(cat, r)
        if widen:
            report.add("info", tr("{label}: widening {w:.2f} m per lane.", label=label, w=widen))
        if norm.arc_fraction_min and (ls_in > 0 or ls_out > 0):
            arc = sum(e.length for e in g.elements if e.is_arc)
            if arc < norm.arc_fraction_min * g.length - 1e-6:
                report.add("warning", tr("{label}: the circle is {a:.1f} m of {t:.1f} m, less than "
                                         "{f:.0%} of the curve.", label=label, a=arc, t=g.length,
                                         f=norm.arc_fraction_min))
    chaining = norm.chaining or {}
    rule = chaining.get("rule")
    for a, b in zip(groups, groups[1:]):
        r1, r2 = a.radius, b.radius
        ratio = float(chaining.get("ratio", 1.5))
        if rule == "ratio_both":
            above = chaining.get("unless_both_above")
            if above is not None and r1 > above and r2 > above:
                continue
            factor = chaining.get("applies_below_factor")
            if factor is not None and rnd is not None and min(r1, r2) >= float(factor) * rnd:
                continue
            if not (1.0 / ratio < r1 / r2 < ratio):
                report.add("warning", tr("C-{a} then C-{b}: radii {r1:.0f} m and {r2:.0f} m, ratio outside "
                                         "{lo:.2f} to {hi:.2f}.", a=a.number, b=b.number, r1=r1, r2=r2,
                                         lo=1.0 / ratio, hi=ratio))
        elif rule == "ratio_next" and rnd is not None:
            limit = float(chaining.get("applies_below_factor", 1.5)) * rnd
            # in both directions of travel: the curve met second may not be
            # much tighter than the one before it
            for first, second in ((a, b), (b, a)):
                if second.radius < limit and first.radius > ratio * second.radius:
                    report.add("warning", tr("C-{a} then C-{b}: R1 = {r1:.0f} m > {k:g} x R2 = {r2:.0f} m.",
                                             a=first.number, b=second.number, r1=first.radius, k=ratio,
                                             r2=second.radius))
    return report


def check_vertical(profile, norm: Norm, category: str, report: Report | None = None) -> Report:
    """A vertical alignment (:class:`vertical.VerticalAlignment`) against
    the standard: every grade against the maximum, every crest and sag
    radius against its minimum."""
    cat_name = norm.category_name(category)
    cat = norm.categories[cat_name]
    report = report or Report(norm, cat_name)
    gmax, crest, sag = cat.get("grade_max"), cat.get("crest_min"), cat.get("sag_min")
    for n, slope in enumerate(profile.slopes(), 1):
        if gmax is not None and abs(slope) * 100.0 > gmax + 1e-9:
            report.add("error", tr("Grade {n}: {p:+.2f} %, steeper than {m:g} %.", n=n, p=slope * 100.0, m=gmax))
    for v in profile.curves():
        limit = crest if v.crest else sag
        kind = tr("crest") if v.crest else tr("sag")
        if v.radius <= 0:
            report.add("warning", tr("S{n} ({kind}): no vertical curve.", n=v.number, kind=kind))
        elif limit is not None and v.radius < limit - 1e-6:
            report.add("error", tr("S{n} ({kind}): R = {r:.0f} m, below the minimum {m:g} m.",
                                   n=v.number, kind=kind, r=v.radius, m=limit))
        else:
            report.add("info", tr("S{n} ({kind}): R = {r:.0f} m.", n=v.number, kind=kind, r=v.radius))
    return report
