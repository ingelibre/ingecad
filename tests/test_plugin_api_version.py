# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""A plugin written for a newer plugin contract is listed, not loaded.

A third-party plugin that used hooks this IngeCAD did not have failed
half-way through its activation, or later, inside a command. It now says
which contract level it needs, and the host refuses it with that reason.
"""
from __future__ import annotations

import textwrap

from core import plugins


class _Host:
    def __init__(self):
        self.commands = {}

    def register_command(self, name, handler):
        self.commands[name.upper()] = handler

    def unregister_command(self, name):
        self.commands.pop(name.upper(), None)

    def register_tools(self, mapping, owner):
        pass

    def unregister_tools(self, names, owner):
        pass

    def add_alias(self, alias, command):
        return True

    def remove_alias(self, alias):
        pass

    def add_pack_dir(self, path):
        pass

    def remove_pack_dir(self, path):
        pass

    def add_toolbar(self, spec):
        pass

    def remove_toolbar(self, plugin_id):
        pass

    def menus_changed(self):
        pass

    def echo(self, text):
        pass


def _plugin(folder, ident, level):
    target = folder / ident
    target.mkdir()
    api = "" if level is None else f", api_version={level!r}"
    (target / "__init__.py").write_text(textwrap.dedent(f"""
        from core.plugins import PluginSpec
        PLUGIN = PluginSpec(id={ident!r}, name="Test",
                            commands={{"PING": lambda ctx: None}}{api})
    """))


def _manager(tmp_path):
    bundled = tmp_path / "bundled"
    user = tmp_path / "user"
    bundled.mkdir()
    user.mkdir()
    return plugins.PluginManager(_Host(), bundled_dir=bundled,
                                 user_dir=user), user


def test_a_plugin_for_a_newer_contract_is_refused_with_the_reason(tmp_path):
    manager, user = _manager(tmp_path)
    _plugin(user, "newer", plugins.API_VERSION + 1)
    manager.discover()
    loaded = manager.loaded["newer"]
    assert not loaded.available
    assert f"plugin API {plugins.API_VERSION + 1}" in loaded.reason
    assert not manager.activate("newer")
    assert "PING" not in manager.host.commands
    assert ("newer", loaded.reason) in manager.problems()


def test_a_plugin_for_this_or_an_older_contract_runs(tmp_path):
    manager, user = _manager(tmp_path)
    _plugin(user, "same", plugins.API_VERSION)
    _plugin(user, "first", 1)
    _plugin(user, "unstated", None)
    manager.discover()
    for ident in ("same", "first", "unstated"):
        assert manager.loaded[ident].available, ident
        assert manager.activate(ident)
    assert "PING" in manager.host.commands


def test_a_nonsense_level_reads_as_the_first(tmp_path):
    manager, user = _manager(tmp_path)
    _plugin(user, "odd", "2")
    manager.discover()
    assert manager.loaded["odd"].available
