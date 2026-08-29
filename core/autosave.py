# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Automatic save and crash recovery — AutoCAD's SAVETIME and .sv$ files.

What AutoCAD does, and what this mirrors:

* **SAVETIME** (reference p. 2500): an integer, minutes, initial value 10,
  0 turns it off, kept in the registry (here: QSettings). "The SAVETIME
  timer starts as soon as you make a change to a drawing. It is reset and
  restarted by a manual QSAVE, SAVE, or SAVEAS."
* The drawing is written to **SAVEFILEPATH** under the name in
  **SAVEFILE** — an ``.sv$`` file beside, not on top of, the user's drawing.
* After a crash the **Drawing Recovery Manager** (DRAWINGRECOVERY, p. 659)
  lists what was open, offering the autosave file next to the original.
* A normal exit leaves nothing behind: the autosave file is deleted.

The one thing that is ours, because the measurement demanded it: writing a
real plan takes **1.0 to 2.2 seconds** (measured: 88 897 entities -> 2.2 s,
41 347 -> 1.0 s), which as a freeze every ten minutes is exactly what the
user asked not to have. So the write runs on a worker thread and the app
only blocks if an edit arrives while it is running -- and the sidecar file
records what it is a copy of, so recovery can tell.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Optional

#: AutoCAD's SAVETIME default and its range, in minutes.
DEFAULT_SAVETIME = 10
MIN_SAVETIME = 0
MAX_SAVETIME = 600

#: AutoCAD's extension for an automatic save.
SUFFIX = ".sv$"
#: The sidecar that says which drawing an .sv$ belongs to, and when.
INFO_SUFFIX = ".sv$.json"


def savetime() -> int:
    """SAVETIME: minutes between automatic saves, 0 = off."""
    from PySide6.QtCore import QSettings

    try:
        value = int(QSettings().value("autosave/savetime", DEFAULT_SAVETIME))
    except (TypeError, ValueError):
        value = DEFAULT_SAVETIME
    return max(MIN_SAVETIME, min(MAX_SAVETIME, value))


def set_savetime(minutes: int) -> int:
    from PySide6.QtCore import QSettings

    value = max(MIN_SAVETIME, min(MAX_SAVETIME, int(minutes)))
    QSettings().setValue("autosave/savetime", value)
    return value


def save_file_path() -> Path:
    """SAVEFILEPATH: where the automatic saves live.

    Not next to the drawing: a plan often sits on a pen drive or a shared
    folder the user cannot write to, and AutoCAD keeps its own directory
    for the same reason.
    """
    from PySide6.QtCore import QSettings, QStandardPaths

    stored = QSettings().value("autosave/path", "")
    if stored:
        return Path(str(stored))
    # The GENERIC data location plus our own name, not AppLocalDataLocation:
    # that one appends whatever the application is called at the moment, and
    # in a script that has not named itself it lands in a folder named after
    # the script. Recovery files must be in one place, always the same one.
    base = QStandardPaths.writableLocation(QStandardPaths.GenericDataLocation)
    if not base:
        base = str(Path.home() / ".local" / "share")
    return Path(base) / "IngeCAD" / "autosave"


def _stem_for(path: Optional[Path]) -> str:
    """The name an autosave takes, unique per drawing and per session.

    AutoCAD's is ``<drawing>_1_1_<session>.sv$``. Ours keeps the drawing's
    name for the recovery list to read, plus the pid so two IngeCAD windows
    on the same file never fight over one file.
    """
    name = path.stem if path is not None else "Untitled"
    safe = "".join(c if c.isalnum() or c in "-_. " else "_" for c in name)
    return f"{safe}_{os.getpid()}"


def autosave_paths(path: Optional[Path]) -> tuple[Path, Path]:
    """(.sv$, .sv$.json) for this drawing in this session."""
    directory = save_file_path()
    stem = _stem_for(path)
    return directory / (stem + SUFFIX), directory / (stem + INFO_SUFFIX)


def write_info(info_path: Path, drawing: Optional[Path], entities: int) -> None:
    """The sidecar the recovery list reads: what, from where, and when."""
    info = {
        "drawing": str(drawing) if drawing else "",
        "saved_at": time.time(),
        "entities": int(entities),
        "pid": os.getpid(),
    }
    info_path.parent.mkdir(parents=True, exist_ok=True)
    info_path.write_text(json.dumps(info), encoding="utf-8")


def discard(sv_path: Path, info_path: Path) -> None:
    """A clean exit or a real save leaves nothing behind."""
    for candidate in (sv_path, info_path):
        try:
            candidate.unlink()
        except OSError:
            pass


def _process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except (OSError, TypeError):
        return False
    return True


def recoverable(directory: Optional[Path] = None) -> list[dict]:
    """Autosave files left behind by a session that never finished.

    A file whose process is still running belongs to another live IngeCAD
    window, not to a crash, and is left alone. Newest first, which is the
    order the Drawing Recovery Manager lists them in.
    """
    directory = Path(directory) if directory is not None else save_file_path()
    found: list[dict] = []
    if not directory.is_dir():
        return found
    for sv in sorted(directory.glob("*" + SUFFIX)):
        if sv.name.endswith(INFO_SUFFIX):
            continue
        info_path = sv.with_name(sv.name + ".json")
        info: dict = {}
        if info_path.is_file():
            try:
                info = json.loads(info_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                info = {}
        pid = info.get("pid")
        if isinstance(pid, int) and pid != os.getpid() and _process_alive(pid):
            continue        # another window has it open right now
        if pid == os.getpid():
            continue        # our own, still being written
        try:
            stat = sv.stat()
        except OSError:
            continue
        found.append({
            "autosave": sv,
            "info": info_path if info_path.is_file() else None,
            "drawing": Path(info["drawing"]) if info.get("drawing") else None,
            "saved_at": float(info.get("saved_at", stat.st_mtime)),
            "entities": int(info.get("entities", 0)),
            "size": stat.st_size,
        })
    found.sort(key=lambda item: item["saved_at"], reverse=True)
    return found


def forget(entry: dict) -> None:
    """Remove one entry from the recovery list, files and all."""
    discard(entry.get("autosave"), entry.get("info") or Path(os.devnull))
