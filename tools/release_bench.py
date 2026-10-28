# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Measure performance before a release: this tree against the last tag.

Marco's golden rule (2026-09-27): "antes de un release siempre deberíamos
medir el rendimiento primero" -- the audit before v0.6.4 found 7-second
freezes that were already in the published v0.6.3, and they only showed up
in the everyday actions, not in opening and zooming.

    tools/release_bench.py compare [--base v0.6.4] [--runs 3] PLAN.dwg ...

checks the base tag out in a worktree, runs every plan through the REAL
window in both trees -- one process per plan and tree, one at a time, since
two IngeCADs on a 10 000-object plan already fill the memory -- and prints
them side by side. A row is flagged when this tree freezes the GUI for
more than a second, or is clearly slower than the base (25 % and 0.2 s).

What is measured, each timed until the screen settles, and the freeze as
the longest gap in a 10 ms event-loop timer (with main()'s switch
interval: without it a worker thread starves the GUI and the numbers lie):
open, a full regen, zoom/pan frames (forced with grabFramebuffer), hover
with LINE running, crossing selection, colour change, Ctrl+C/X/V, ERASE,
COPY, MOVE -- each undone -- and Save as DWG.

Needs a display: DISPLAY=:0 QT_QPA_PLATFORM=xcb (offscreen does not paint).
Keep TMPDIR on disk (/tmp is RAM): the DWG round trips are large.

    tools/release_bench.py run PLAN.dwg OUT.jsonl TREE   (one child run)
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: Everyday actions: (key, label) in the order they run.
ACTIONS = [
    ("open", "open"), ("regen", "full regen"),
    ("select", "crossing selection"), ("color", "colour change"),
    ("undo_color", "  undo"), ("copyclip", "Ctrl+C"), ("erase", "ERASE"),
    ("undo_erase", "  undo"), ("paste", "Ctrl+V"), ("undo_paste", "  undo"),
    ("cut", "Ctrl+X"), ("undo_cut", "  undo"), ("copy", "COPY"),
    ("undo_copy", "  undo"), ("move", "MOVE"), ("undo_move", "  undo"),
    ("save_dwg", "Save as DWG"),
]
FREEZE_LIMIT = 1.0          # seconds the GUI may not answer
PAINT_LIMIT = 0.3           # an empty paint slower than this: a paced display
SLOWER = 1.25               # ...and how much slower than the base is a flag
SLOWER_ABS = 0.2


# -- one plan, one tree: runs INSIDE the tree being measured ------------------------
def run_one(src: Path, out: Path, tree: str) -> dict:
    import faulthandler
    import random

    sys.setswitchinterval(0.001)        # as main() sets it for the real app
    faulthandler.dump_traceback_later(
        int(os.environ.get("BENCH_WATCHDOG", "1500")), exit=True,
        file=open(str(out) + ".stack", "w"))
    from PySide6.QtCore import QCoreApplication, QTimer
    QCoreApplication.setOrganizationName("IngeCAD-bench")
    QCoreApplication.setApplicationName("IngeCAD-bench")
    from PySide6.QtWidgets import QApplication
    app = QApplication([])
    from core import actions
    from views.main_window import MainWindow

    res: dict = {"tree": tree, "file": src.name}
    win = MainWindow()
    win.resize(1400, 900)
    win.show()
    win.maybe_save_changes = lambda: True
    from PySide6.QtWidgets import QMessageBox
    QMessageBox.warning = staticmethod(lambda *a, **k: None)   # modal: would hang
    tc, vp = win.tools, win.viewport

    gap = {"last": None, "worst": 0.0}

    def tick():
        now = time.monotonic()
        if gap["last"] is not None:
            gap["worst"] = max(gap["worst"], now - gap["last"])
        gap["last"] = now

    timer = QTimer()
    timer.setInterval(10)
    timer.timeout.connect(tick)
    timer.start()

    def idle() -> bool:
        return (win._open_thread is None
                and getattr(win, "_regen_worker", None) is None
                and not getattr(tc, "_warmers", None))

    def settle(timeout=600.0):
        t = time.monotonic()
        while time.monotonic() - t < timeout:
            app.processEvents()
            if idle():
                break
        app.processEvents()
        vp.grabFramebuffer()

    def empty_paint() -> float:
        t = time.perf_counter()
        vp.update()
        app.processEvents()
        vp.grabFramebuffer()
        return time.perf_counter() - t

    def timed(key, fn):
        t = time.monotonic()
        gap["last"], gap["worst"] = time.monotonic(), 0.0
        try:
            fn()
            settle()
            # the timer's worst gap alone: a call that blocks shows up as
            # the gap to the first tick after it, and a call that keeps the
            # loop turning (Ctrl+S's local loop) is not a freeze
            res[key] = {"total": round(time.monotonic() - t, 2),
                        "freeze": round(gap["worst"], 2)}
            # the compositor can start pacing mid-run (the window covered
            # or the screen blanked): the 0.6.6 bench read exact 1.00 s
            # steps in both trees, all of them waiting in the GL swap. An
            # empty paint after each action says whether this sample counts.
            if empty_paint() > PAINT_LIMIT:
                res[key]["paced"] = True
        except Exception as exc:  # noqa: BLE001 - a failure IS a result
            res[key] = f"FAIL {type(exc).__name__}: {str(exc)[:80]}"
            settle()

    for _ in range(20):
        app.processEvents()
    # A locked or blanked screen makes GNOME pace this window at one frame
    # a second: every paint then blocks ~1 s inside processEvents and every
    # action reads 1.00, 2.00, 3.00 s, in both trees alike (2026-10-09, the
    # 0.6.6 bench run while Marco was away). Measure a few empty paints
    # first and say so, rather than report the compositor as freezes.
    paints = [empty_paint() for _ in range(5)]
    res["paint_s"] = round(statistics.median(paints), 3)
    timed("open", lambda: win.open_path(src))
    res["entities"] = len(win.document.modelspace())
    vp.zoom_extents()
    settle()
    timed("regen", win.regen_in_memory)

    def ms(xs):
        xs = sorted(xs)
        return {"med": round(statistics.median(xs), 1),
                "p95": round(xs[max(0, int(len(xs) * .95) - 1)], 1),
                "max": round(xs[-1], 1)}

    random.seed(1)
    frames = []
    for i in range(40):
        f = 1.15 if i < 20 else 1 / 1.15
        vp.view.zoom_at(vp.width() / 2 + random.uniform(-200, 200), vp.height() / 2, f)
        t = time.perf_counter()
        vp.grabFramebuffer()
        frames.append((time.perf_counter() - t) * 1000)
    vp.zoom_extents()
    for _ in range(30):
        vp.view.pan_pixels(vp.width() * 0.02, 0)
        t = time.perf_counter()
        vp.grabFramebuffer()
        frames.append((time.perf_counter() - t) * 1000)
    res["frame_ms"] = ms(frames)
    vp.zoom_extents()
    settle()

    w, h = vp.width(), vp.height()
    tc.start_tool("LINE")
    cx, cy = vp.view.screen_to_world(w / 2, h / 2)
    win._on_command_submitted(f"{cx},{cy}")
    hover = []
    for _ in range(300):
        wx, wy = vp.view.screen_to_world(random.uniform(0, w), random.uniform(0, h))
        t = time.perf_counter()
        tc.on_hover(wx, wy)
        hover.append((time.perf_counter() - t) * 1000)
    res["hover_ms"] = ms(hover)
    tc.cancel()
    settle()

    tl = vp.view.screen_to_world(5, 5)
    br = vp.view.screen_to_world(w - 5, h - 5)

    def crossing():
        tc.cancel()
        tc.selection = set()
        tc.on_click(br[0], tl[1])            # right to left: crossing
        tc.on_click(tl[0], br[1])

    timed("select", crossing)
    res["selected"] = len(tc.selection)
    timed("color", lambda: win._apply_property("color", 1))
    timed("undo_color", win._cmd_undo)
    crossing()
    timed("copyclip", win._cmd_copy)
    timed("erase", lambda: win._on_command_submitted("ERASE"))
    timed("undo_erase", win._cmd_undo)

    def paste():
        win._cmd_paste()
        px, py = vp.view.screen_to_world(w * 0.6, h * 0.6)
        tc.on_click(px, py)

    timed("paste", paste)
    timed("undo_paste", win._cmd_undo)
    crossing()
    timed("cut", win._cmd_cut)
    timed("undo_cut", win._cmd_undo)
    crossing()

    def copy_cmd():
        for text in ("COPY", "0,0", "@100,0", ""):
            win._on_command_submitted(text)

    timed("copy", copy_cmd)
    timed("undo_copy", win._cmd_undo)
    some = list(win.document.modelspace())[:200]
    timed("move", lambda: tc._execute(actions.move_entities(some, 5.0, 5.0)))
    timed("undo_move", win._cmd_undo)
    folder = Path(tempfile.mkdtemp(dir=os.environ.get("TMPDIR")))
    # the window's own path, as Ctrl+S takes it (warnings are non-modal)
    timed("save_dwg", lambda: win._write_document(folder / "bench.dwg", "r2000"))

    with open(out, "a") as fh:
        fh.write(json.dumps(res) + "\n")
    print(json.dumps(res), flush=True)
    win.document.dirty = False
    os._exit(0)


# -- the comparison: runs from THIS tree ----------------------------------------------
def _worktree(tag: str) -> Path:
    base = Path(os.environ.get("TMPDIR") or tempfile.gettempdir()) / f"ingecad-bench-{tag}"
    if not base.exists():
        subprocess.run(["git", "-C", str(ROOT), "worktree", "add", "--detach",
                        str(base), tag], check=True)
        # vendor/ (LibreDWG) is not tracked: the base uses this tree's
        # converters, so the comparison measures IngeCAD alone
        (base / "vendor").symlink_to(ROOT / "vendor")
    return base


def _child(tree_dir: Path, name: str, plan: Path, out: Path) -> None:
    env = dict(os.environ)
    env.setdefault("QT_QPA_PLATFORM", "xcb")
    env["PYTHONPATH"] = str(tree_dir)
    subprocess.run([sys.executable, str(Path(__file__).resolve()), "run",
                    str(plan), str(out), name], cwd=tree_dir, env=env, check=False)


def _value(row, key):
    """A sample that counts: measured, and not paced by the compositor."""
    v = row.get(key)
    return v if isinstance(v, dict) and not v.get("paced") else None


def _paced(rows, key) -> int:
    return sum(1 for r in rows if isinstance(r.get(key), dict) and r[key].get("paced"))


def _median(rows, key, field):
    xs = [v[field] for r in rows if (v := _value(r, key)) is not None]
    return statistics.median(xs) if xs else None


def report(results: dict[str, dict[str, list]], base: str) -> int:
    flags = 0
    throttled = sorted({r["tree"] for trees in results.values()
                        for rows in trees.values() for r in rows
                        if r.get("paint_s", 0) > PAINT_LIMIT})
    if throttled:
        print("\n!! The display paced the window (an empty paint took over "
              f"{PAINT_LIMIT} s) in: {', '.join(throttled)}.\n!! Is the screen "
              "locked or blank? Freezes below are the compositor, not IngeCAD: "
              "run again with the screen on.")
    for plan, trees in results.items():
        head, old = trees.get("HEAD", []), trees.get(base, [])
        ents = next((r.get("entities") for r in head if "entities" in r), "?")
        print(f"\n{plan}  ({ents} objects)   seconds until the screen settles "
              f"(worst GUI freeze), median of {len(head)} run(s)")
        print(f"  {'action':<20}{base:>18}{'HEAD':>18}")
        for key, label in ACTIONS:
            bt, bf = _median(old, key, "total"), _median(old, key, "freeze")
            ht, hf = _median(head, key, "total"), _median(head, key, "freeze")
            fails = sorted({str(r[key]) for r in head if isinstance(r.get(key), str)})
            cell = lambda t, f: "—" if t is None else f"{t:.2f} ({f:.2f})"
            mark = ""
            paced = _paced(old, key) + _paced(head, key)
            if paced:
                mark = f"  ({paced} paced sample(s) left out)"
            if fails:
                mark = "  FAIL " + fails[0]
            elif hf is not None and hf > FREEZE_LIMIT:
                mark = f"  ⚠ freezes {hf:.1f} s"
            elif (ht is not None and bt is not None and ht > bt * SLOWER
                    and ht - bt > SLOWER_ABS):
                mark = f"  ⚠ slower than {base}"
            flags += bool(mark) and not mark.startswith("  (")
            print(f"  {label:<20}{cell(bt, bf):>18}{cell(ht, hf):>18}{mark}")
        for key in ("frame_ms", "hover_ms"):
            b = [r[key]["med"] for r in old if key in r]
            h = [r[key]["med"] for r in head if key in r]
            if b or h:
                print(f"  {key:<20}{(statistics.median(b) if b else 0):>15.1f} ms"
                      f"{(statistics.median(h) if h else 0):>15.1f} ms")
    print(f"\n{flags} flag(s).")
    return 1 if flags or throttled else 0


def compare(plans: list[Path], base: str, runs: int, out: Path) -> int:
    base_dir = _worktree(base)
    results: dict[str, dict[str, list]] = {}
    for plan in plans:
        # alternated, so a spell of a paced display hits both trees alike
        for _ in range(runs):
            for name, tree in ((base, base_dir), ("HEAD", ROOT)):
                before = out.read_text().count("\n") if out.exists() else 0
                _child(tree, name, plan, out)
                lines = out.read_text().splitlines() if out.exists() else []
                for line in lines[before:]:
                    row = json.loads(line)
                    results.setdefault(plan.name, {}).setdefault(name, []).append(row)
    return report(results, base)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="mode", required=True)
    c = sub.add_parser("compare", help="HEAD against a tag, side by side")
    c.add_argument("plans", nargs="+", type=Path)
    c.add_argument("--base", default=None, help="tag to compare with (last tag)")
    c.add_argument("--runs", type=int, default=1)
    c.add_argument("--out", type=Path, default=None)
    r = sub.add_parser("run", help="one plan in the current tree (internal)")
    r.add_argument("plan", type=Path)
    r.add_argument("out", type=Path)
    r.add_argument("tree")
    args = ap.parse_args(argv)
    if args.mode == "run":
        # the tree being measured, not the folder this script lives in
        here = str(Path(__file__).resolve().parent)
        sys.path[:] = [p for p in sys.path if p != here]
        sys.path.insert(0, os.getcwd())
        return run_one(args.plan.resolve(), args.out, args.tree) or 0
    base = args.base or subprocess.run(
        ["git", "-C", str(ROOT), "describe", "--tags", "--abbrev=0"],
        capture_output=True, text=True, check=True).stdout.strip()
    out = args.out or Path(tempfile.mkstemp(suffix=".jsonl",
                                            dir=os.environ.get("TMPDIR"))[1])
    print(f"results: {out}")
    return compare([p.resolve() for p in args.plans], base, args.runs, out)


if __name__ == "__main__":
    sys.exit(main())
