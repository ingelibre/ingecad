# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Spanish stays complete, and no translation loses a {placeholder}.

Spanish is the language this project maintains, so a string reaching the user
untranslated is a defect here -- es.json fell a whole release behind while
v0.3 and v0.4 added tables, images, QuickCalc, QSELECT and the options dialog,
and nothing said so (issue #3). Community languages are *reported*, never
enforced: a missing key falls back to the English source, so an incomplete
file degrades to readable English and must never block a release.

The placeholder check applies to every language, because it is not a matter of
completeness but of crashing: ``tr("{count} found", count=3)`` formats the
translation, so a Spanish string that spells ``{cout}`` raises KeyError in
front of the user, and one that drops ``{count}`` silently swallows the number.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from core import i18n  # noqa: E402

SKIP_DIRS = {"build", "web", "vendor", ".venv", "venv", "externos", "tests"}


def _maintained() -> list[str]:
    """Languages whose pack says the project keeps them complete.

    Read from ``meta.json`` rather than hard-coded here, so adding a language
    touches no Python at all -- not even this test.
    """
    return sorted(p.code for p in i18n.language_packs().values()
                  if p.maintained and p.catalog is not None)


MAINTAINED = _maintained()


def _scan() -> tuple[dict[str, str], set[str]]:
    """(literals passed to tr(), every string literal in the sources).

    The second set matters: plenty of translated text never appears inside a
    ``tr(...)`` call, because it lives in a data table and is translated later
    through a variable -- ``Mode("END", 1, "Endpoint")`` in ``core/osnap.py``
    reaches ``tr(mode.label)``. 106 keys are like that. A dead-key check that
    only knew about ``tr()`` literals would demand their deletion and quietly
    un-translate the osnap markers.
    """
    calls: dict[str, str] = {}
    literals: set[str] = set()
    for path in sorted(ROOT.rglob("*.py")):
        if SKIP_DIRS & set(path.parts):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                literals.add(node.value)
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name) and node.func.id == "tr"
                    and node.args):
                continue
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                calls.setdefault(first.value,
                                 f"{path.relative_to(ROOT)}:{node.lineno}")
    return calls, literals


def _sources() -> dict[str, str]:
    """Literals passed straight to tr(), mapped to where they appear.

    Text reaching tr() through a variable cannot be found statically, so this
    is what the coverage tests can honestly promise: every *literal* call.
    """
    return _scan()[0]


def _catalog(lang: str) -> dict[str, str]:
    return i18n.language_packs()[lang].load()


def _fields(text: str) -> list[str]:
    return sorted(re.findall(r"\{[^{}]*\}", text))


def test_the_scanner_finds_the_strings_it_is_supposed_to() -> None:
    """A scanner that silently found nothing would make every test below pass."""
    sources = _sources()
    assert len(sources) > 500, f"only {len(sources)} tr() strings found"
    assert "File" in sources


@pytest.mark.parametrize("lang", MAINTAINED)
def test_maintained_language_translates_every_string(lang: str) -> None:
    sources = _sources()
    catalog = _catalog(lang)
    missing = {s: where for s, where in sources.items() if s not in catalog}
    assert not missing, (
        f"{lang}.json is missing {len(missing)} string(s); the user sees them "
        f"in English:\n"
        + "\n".join(f"  [{where}] {text!r}"
                    for text, where in sorted(missing.items(),
                                              key=lambda kv: kv[1])[:40]))


@pytest.mark.parametrize("lang", MAINTAINED)
def test_maintained_language_has_no_dead_keys(lang: str) -> None:
    """A key that matches no string in the sources is a typo or a leftover.

    A typo is the dangerous one: the misspelt key translates nothing and the
    real string keeps reaching the user in English, which is exactly the
    failure this file exists to catch. 32 leftovers were removed when this
    test was written -- prompts reworded during the draw-command audit, whose
    old wording stayed behind in es.json.
    """
    calls, literals = _scan()
    dead = sorted(k for k in _catalog(lang)
                  if k not in calls and k not in literals)
    assert not dead, (
        f"{lang}.json has {len(dead)} key(s) that match no string in the "
        f"sources -- a typo here leaves the real string untranslated:\n"
        + "\n".join(f"  {k!r}" for k in dead[:40]))


def _languages() -> list[str]:
    """Installed languages that carry a catalog (the source language has none)."""
    return sorted(p.code for p in i18n.language_packs().values()
                  if p.catalog is not None)


@pytest.mark.parametrize("lang", _languages())
def test_every_translation_keeps_its_placeholders(lang: str) -> None:
    wrong = []
    for source, translation in _catalog(lang).items():
        if _fields(source) != _fields(translation):
            wrong.append(f"  {source!r}\n    -> {translation!r}\n"
                         f"       {_fields(source)} became {_fields(translation)}")
    assert not wrong, (
        f"{lang}.json: {len(wrong)} translation(s) changed their placeholders; "
        f"tr() formats the translation, so this raises or drops data at "
        f"runtime.\n" + "\n".join(wrong))


def test_coverage_report(capsys) -> None:
    """Not an assertion: what each community language still has left."""
    sources = _sources()
    lines = []
    for lang in _languages():
        catalog = _catalog(lang)
        done = sum(1 for s in sources if s in catalog)
        lines.append(f"  {lang}: {done}/{len(sources)} "
                     f"({100 * done / len(sources):.0f}%)"
                     + ("  [maintained]" if lang in MAINTAINED else ""))
    with capsys.disabled():
        print("\ntranslation coverage\n" + "\n".join(lines))
