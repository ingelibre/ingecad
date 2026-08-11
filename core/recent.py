# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The recent-drawings list, and where its thumbnails are cached.

Plain JSON under the user's config directory rather than QSettings: this
module stays importable without Qt, like the rest of ``core`` (the headless
invariant — every command has to be testable without a GUI).

A drawing that no longer exists is dropped on read, not on write: a plan
that lives on a memory stick should not vanish from the list because it
happened to be unplugged when the app started.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

MAX_RECENT = 12


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "IngeCAD"


def cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "IngeCAD"


def _store() -> Path:
    return config_dir() / "recent.json"


def _read_raw() -> list[str]:
    try:
        data = json.loads(_store().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    return [str(item) for item in data if isinstance(item, str)]


def _write_raw(paths: list[str]) -> None:
    store = _store()
    try:
        store.parent.mkdir(parents=True, exist_ok=True)
        store.write_text(json.dumps(paths, indent=2, ensure_ascii=False),
                         encoding="utf-8")
    except OSError:
        pass          # a read-only home must not break saving a drawing


def load(existing_only: bool = True) -> list[Path]:
    """Most recent first."""
    paths = [Path(p) for p in _read_raw()]
    if existing_only:
        paths = [p for p in paths if p.exists()]
    return paths[:MAX_RECENT]


def add(path) -> list[Path]:
    """Put a drawing at the top of the list and return the new list."""
    path = Path(path).expanduser()
    try:
        path = path.resolve()
    except OSError:
        pass
    kept = [p for p in _read_raw() if p != str(path)]
    kept.insert(0, str(path))
    _write_raw(kept[:MAX_RECENT])
    return load()


def remove(path) -> list[Path]:
    target = str(Path(path))
    _write_raw([p for p in _read_raw() if p != target])
    return load()


def clear() -> None:
    _write_raw([])


def thumbnail_path(path) -> Path:
    """Where this drawing's thumbnail is cached.

    Keyed by the path AND its modification time, so an edited drawing gets a
    fresh thumbnail instead of showing yesterday's plan.
    """
    path = Path(path)
    try:
        stamp = str(int(path.stat().st_mtime))
    except OSError:
        stamp = "0"
    digest = hashlib.sha1(
        f"{path}|{stamp}".encode("utf-8", "replace")).hexdigest()[:16]
    return cache_dir() / "thumbnails" / f"{digest}.png"
