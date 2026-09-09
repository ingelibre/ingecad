# SPDX-License-Identifier: GPL-3.0-or-later
"""Recovering from a driver that will not give us a GL context.

The machine that reported this (Ubuntu 24.04 + GNOME 46 on Wayland, NVIDIA
Quadro P600, 2026-09-09) is not one CI can rent, so what is pinned here is
the DECISION TABLE around the probe, with the probe itself stubbed: which
outcome each situation produces, and above all that the process never
restarts itself twice. Kept in step with IngeTrazo's copy of this file.
"""
from __future__ import annotations

import os

import pytest
from PySide6.QtGui import QSurfaceFormat

from core import gl_fallback


class _App:
    """Stands in for the QApplication: the probe only asks it one thing."""

    def __init__(self, platform="wayland"):
        self._platform = platform

    def platformName(self):
        return self._platform


class _Executed(Exception):
    """os.execv does not return; this is how the stub says it was reached."""


def _never(*_args, **_kwargs):
    raise AssertionError("the process restarted when it should not have")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv(gl_fallback.GUARD_ENV, raising=False)
    monkeypatch.setenv("DISPLAY", ":0")
    # Both of these are process-wide, and the code under test writes to
    # them for real: registering them with monkeypatch is what puts them
    # back for whatever test file runs next in the same interpreter.
    monkeypatch.setenv("QT_QPA_PLATFORM",
                       os.environ.get("QT_QPA_PLATFORM", "offscreen"))
    original = QSurfaceFormat.defaultFormat()
    yield
    QSurfaceFormat.setDefaultFormat(original)


def _format(samples=4):
    """What main._configure_surface_format asks for: 3.3 core, smoothed,
    and no depth buffer (the canvas is 2D and draws back to front)."""
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.CoreProfile)
    if samples:
        fmt.setSamples(samples)
    return fmt


# ---- the leaner format ----------------------------------------------------

def test_leaner_gives_up_line_smoothing_and_keeps_the_context_version():
    lean = gl_fallback.leaner(_format(samples=4))
    assert lean.samples() == 0
    assert lean.majorVersion() == 3 and lean.minorVersion() == 3
    assert lean.profile() == QSurfaceFormat.CoreProfile, "GLSL 330 needs it"


def test_leaner_says_so_when_there_is_nothing_left_to_drop():
    assert gl_fallback.leaner(_format(samples=0)) is None


# ---- the decision table ---------------------------------------------------

def test_a_working_driver_costs_one_probe_and_nothing_else(monkeypatch):
    monkeypatch.setattr(gl_fallback, "_can_create", lambda fmt: True)
    monkeypatch.setattr(os, "execv", _never)
    assert gl_fallback.ensure_gl_context(_App()) == "ok"


def test_dropping_the_smoothing_is_tried_before_leaving_wayland(monkeypatch):
    QSurfaceFormat.setDefaultFormat(_format(samples=4))
    monkeypatch.setattr(gl_fallback, "_can_create",
                        lambda fmt: fmt.samples() <= 0)
    monkeypatch.setattr(os, "execv", _never)

    assert gl_fallback.ensure_gl_context(_App()) == "reduced"
    # And it becomes the format every later window is built with.
    assert QSurfaceFormat.defaultFormat().samples() <= 0


def test_no_context_at_all_restarts_under_xcb(monkeypatch):
    QSurfaceFormat.setDefaultFormat(_format())
    monkeypatch.setattr(gl_fallback, "_can_create", lambda fmt: False)

    def _fake_execv(path, argv):
        raise _Executed

    monkeypatch.setattr(os, "execv", _fake_execv)
    with pytest.raises(_Executed):
        gl_fallback.ensure_gl_context(_App())
    assert os.environ["QT_QPA_PLATFORM"] == "xcb"
    assert os.environ[gl_fallback.GUARD_ENV] == "1"


def test_the_restarted_process_does_not_restart_again(monkeypatch):
    """The point of the guard: no loop where X11 fails too."""
    QSurfaceFormat.setDefaultFormat(_format())
    monkeypatch.setenv(gl_fallback.GUARD_ENV, "1")
    monkeypatch.setattr(gl_fallback, "_can_create", lambda fmt: False)
    monkeypatch.setattr(os, "execv", _never)
    assert gl_fallback.ensure_gl_context(_App(platform="xcb")) == "failed"


def test_already_on_x11_has_nowhere_to_go(monkeypatch):
    QSurfaceFormat.setDefaultFormat(_format())
    monkeypatch.setattr(gl_fallback, "_can_create", lambda fmt: False)
    monkeypatch.setattr(os, "execv", _never)
    assert gl_fallback.ensure_gl_context(_App(platform="xcb")) == "failed"


def test_wayland_without_xwayland_says_so_instead_of_restarting(monkeypatch):
    """A Flatpak given only --socket=fallback-x11 lands here: Wayland is up,
    so the X11 socket was never handed over and DISPLAY is empty."""
    QSurfaceFormat.setDefaultFormat(_format())
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.setattr(gl_fallback, "_can_create", lambda fmt: False)
    monkeypatch.setattr(os, "execv", _never)
    assert gl_fallback.ensure_gl_context(_App()) == "no-x11"


def test_the_restarted_process_reports_that_it_is_the_xcb_one(monkeypatch):
    monkeypatch.setenv(gl_fallback.GUARD_ENV, "1")
    monkeypatch.setattr(gl_fallback, "_can_create", lambda fmt: True)
    monkeypatch.setattr(os, "execv", _never)
    assert gl_fallback.ensure_gl_context(_App(platform="xcb")) == "xcb"
