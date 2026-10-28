# Plugins — the contract

IngeCAD's core is the classic 2D CAD. Everything a discipline adds
(topography, terrain, water and sewer networks, roads) is a **plugin**: a
folder that, when turned on, adds one menu, its commands and tools, an
optional toolbar and options page, and its own translations — and, when
turned off, removes exactly that. The test suite holds every bundled plugin
to "no trace left" (`tests/test_plugins.py`).

Bundled plugins live in `plugins/<id>/` and ship with the app, on by
default. A plugin's **toolbar is off by default** -- the menu is what a
plugin adds; the user switches the toolbar on in **Tools ▸ Plugins…**
("Show this plugin's toolbar"), and the choice is remembered. A user's own live in `~/.config/IngeCAD/plugins/<id>/`, off until
enabled in **Tools ▸ Plugins…** (command `PLUGINS`).

## The smallest plugin

`plugins/ejemplo/__init__.py` (the suite's fixture is exactly this file,
under `tests/plugins_fixture/ejemplo/`):

```python
from pathlib import Path
from core.plugins import SEPARATOR, MenuItem, PluginSpec, Submenu, ToolbarItem
from tools.base import Tool


class EchoPointTool(Tool):
    def start(self):
        self.name = "ECHOPT"
        self.prompt("Specify a point to echo:")

    def on_point(self, point):
        self.ctx.echo(f"({point[0]:.3f}, {point[1]:.3f})")
        self.ctx.finish()


def hello(ctx, *args):
    ctx.echo("Hello from the sample plugin")


PLUGIN = PluginSpec(
    id="ejemplo",                      # must equal the folder name
    name="Sample",                     # menu title (translated through the pack)
    version="0.1",
    description="One command, one tool, one alias, one menu.",
    commands={"HELLO": hello},         # handler(ctx, *args)
    tools={"ECHOPT": EchoPointTool},   # a Tool gets a starter command for free
    aliases={"HQ": "HELLO"},
    menu=(MenuItem("Say hello", "HELLO"), SEPARATOR,
          Submenu("Points", (MenuItem("Echo a point", "ECHOPT"),))),
    toolbar=(ToolbarItem("Say hello", "HELLO"),),
    i18n_dir=Path(__file__).parent / "i18n",
)
```

with `i18n/es/ui.json` (`{"Say hello": "Saludar", ...}`) and, optionally,
`i18n/es/commands.json` (`{"HELLO": {"name": "HOLA"}}`).

## What each field means

| field | what the host does with it |
|---|---|
| `commands` | `Dispatcher.register(name, handler)`; the handler receives a `PluginContext` first (`ctx.document`, `ctx.execute(command)`, `ctx.start_tool(name)`, `ctx.echo(text)`), then the typed arguments |
| `tools` | joins the one registry `ToolController.start_tool` reads, counted per plugin so several windows can share it; a name the core or another plugin owns refuses the whole activation |
| `aliases` | added unless the user's `acad.pgp` or the core already answers to the token — an alias always wins over a command name, so a plugin can never take one |
| `menu` | one top-level menu per plugin, between *Modify* and *Tools*; labels go through `tr()` when the menu is built |
| `toolbar` | a `QToolBar` named `plugin_<id>_toolbar`, top area, movable; `SEPARATOR` between buttons as in a menu |
| `options_page` | `callable(dialog, window) -> QWidget` added as a tab to Options after the core ones; if the widget has `apply()`, it runs with the core pages on OK and on Apply |
| `i18n_dir` | `<dir>/<lang>/ui.json` strings merge after the app's catalog (the app wins a clash); `<dir>/<lang>/commands.json` adds localized command names, English always kept |
| `requires` | module names; a missing one lists the plugin as *unavailable: needs X* instead of breaking start-up |
| `on_document_open` | `callable(ctx, document)` after a drawing is created or opened |

## The rules a plugin lives by

They are the project's own, not extra ones:

1. **Every mutation is a `Command`** with an exact undo, and every operation
   is a headless action (`plugins/<id>/actions.py`, same shape as
   `core/actions.py`). Tools are thin shells over actions.
2. **The ezdxf document is the model.** A plugin writes plain DXF entities
   in named layers; what it must remember (which 3DFACEs form one surface,
   which UTM zone the drawing is in) goes into XDATA. The bundled plugins
   write under the `INGECAD` APPID (`core/xdata.py`); a third-party plugin
   registers its own, `ensure_appid(doc, "MYPLUGIN")`, and never writes
   under `INGECAD`: `set_xdata` replaces everything under an APPID, so it
   would wipe the survey and terrain tags of the same entity. Drawing-wide
   data goes in the root dictionary, under the plugin's own name too (the
   `INGECAD` one holds the core's georeference). What several plugins need to agree on
   lives in the core, once: the drawing's UTM zone, hemisphere and datum (or
   its EPSG coordinate system) are
   `core/georef.py` (`read_georef`, `SetGeorefCommand`), declared by the
   Terrain plugin's GEOREF and read by Topography's reports. The drawing
   opens in any CAD without IngeCAD.
3. **Typed is English, read is translated.** Command names are English with
   additive localized names; menus and prompts go through `tr()`. The
   coverage test (`tests/test_i18n_coverage.py`) checks each bundled
   plugin's `i18n/<lang>/ui.json` against the plugin's own sources.
4. **Heavy imports are deferred** to the first command; the spec module
   itself imports nothing expensive, so start-up does not pay for a plugin.
5. **Tests live in `tests/test_<id>_*.py`**, next to everything else the
   suite runs (`pytest tests/` is what CI executes), and drive the tools
   headless the way `tests/test_topografia_points.py` does.

## Checking an install

`ingecad --check` (or `python main.py --check`) lists the plugins found and
names any bundled one that cannot run — the same silent-loss check the
language packs get.

## Scripts: APPLOAD and SCRIPT

Not everything deserves a plugin. A one-off job -- number two hundred points,
draw a grid, rename layers -- is a **Python file** run with `APPLOAD` (alias
`AP`, Tools > Load Application...). It runs once, right away, with this in
scope:

| name | what it is |
|---|---|
| `actions` | `core.actions`: every headless command (`add_line`, `add_circle`, `TransformCommand`, ...) |
| `execute(cmd)` | run a Command through the history: undoable |
| `command("LINE")` | type something at the command line |
| `document`, `doc`, `msp` | the open drawing, its ezdxf `Drawing`, its modelspace |
| `echo(text)` | write to the command window |
| `ezdxf` | the library itself, for anything `actions` does not cover |

Everything the file executes is folded into **one undo step** named after the
file. A worked example, `grid.py`:

```python
for i in range(11):
    execute(actions.add_line((0, i * 10), (100, i * 10)))
    execute(actions.add_line((i * 10, 0), (i * 10, 100)))
echo("grid drawn")
```

If the script raises, what it did before the error stays (undoable) and the
last line of the traceback is echoed.

`SCRIPT` (alias `SCR`, Tools > Run Script...) runs an AutoCAD `.scr`: one
command-line entry per line, a blank line is Enter, `DELAY 500` waits half a
second, `RSCRIPT` repeats from the top, `;` starts a comment. The script that
worked in AutoCAD works here as long as its commands exist in IngeCAD.

## Worked examples for a plugin

**A command with prompts.** A tool is a `tools.base.Tool` subclass; its
prompts take AutoCAD's wording with the English option letters, and every
mutation goes through `ctx.execute`:

```python
from tools.base import Tool
from core import actions

class Star(Tool):
    name = "STAR"

    def on_start(self):
        self.prompt("Specify center point:")

    def on_point(self, p):
        if self.last_point is None:
            self.last_point = p
            self.prompt("Specify radius or [Points] <5>:")
        else:
            r = ((p[0] - self.last_point[0]) ** 2 + (p[1] - self.last_point[1]) ** 2) ** 0.5
            self.ctx.execute(actions.add_polygon(self.last_point, r, 5))   # one undo step
            self.ctx.finish()
```

Register it in the spec: `tools={"STAR": Star}`, `aliases={"ST": "STAR"}`.

**A menu and a toolbar.** Labels are English and translated through the
plugin's own `i18n/<lang>/ui.json`:

```python
PLUGIN = PluginSpec(
    id="stars", name="Stars", version="0.1",
    tools={"STAR": Star},
    menu=(MenuItem("Star", "STAR"), SEPARATOR,
          Submenu("More", (MenuItem("Big star", "STAR"),))),
    toolbar=(ToolbarItem("Star", "STAR", icon=Path(__file__).parent / "star.svg"),),
)
```

The toolbar is off by default (View > Toolbars turns it on); turning the
plugin off removes the menu, the toolbar, the commands and the aliases, and
`tests/test_plugins.py` holds every bundled plugin to that.
