# Plugins — the contract

IngeCAD's core is the classic 2D CAD. Everything a discipline adds
(topography, terrain, water and sewer networks, roads) is a **plugin**: a
folder that, when turned on, adds one menu, its commands and tools, an
optional toolbar and options page, and its own translations — and, when
turned off, removes exactly that. The test suite holds every bundled plugin
to "no trace left" (`tests/test_plugins.py`).

Bundled plugins live in `plugins/<id>/` and ship with the app, on by
default. A user's own live in `~/.config/IngeCAD/plugins/<id>/`, off until
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
| `toolbar` | a `QToolBar` named `plugin_<id>_toolbar`, top area, movable |
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
   which UTM zone the drawing is in) goes into XDATA under the `INGECAD`
   APPID (`core/xdata.py` owns the name and `ensure_appid`) or the root
   dictionary's `INGECAD` dictionary. What several plugins need to agree on
   lives in the core, once: the drawing's UTM zone, hemisphere and datum are
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
