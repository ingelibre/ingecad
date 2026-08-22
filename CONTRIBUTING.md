# Contributing to IngeCAD

Patches, bug reports and translations are welcome. IngeCAD is
GPL-3.0-or-later; by contributing you agree your work ships under that
licence. Contributors are listed in `AUTHORS`, and the project follows the
[Contributor Covenant](CODE_OF_CONDUCT.md).

**Write in English or Spanish, whichever you prefer** — both are read. Only
the code itself, its comments and the commit messages have to be English, so
that any contributor can read them.

You do not need any permission on this repository to contribute: fork it, push
your change to a branch of your fork, and open a pull request. That is how
every outside change has arrived so far.

## Getting it running

```sh
python3 -m venv venv
venv/bin/pip install -r requirements.txt
venv/bin/python main.py
venv/bin/python -m pytest        # the suite must stay green
```

`venv/bin/python main.py --check` is the self-diagnostic the CI runs: it
verifies the DWG converters and the resource directories are where the app
expects them.

## House rules

- **Code, comments, docstrings and commit messages are in English**, so that
  any contributor can read them. The user interface is translated; see below.
- **Every mutation of the drawing goes through a Command** (`core/commands.py`)
  so that undo and redo are exact, and **every command is a headless action**
  in `core/actions.py` — never logic attached to a key or mouse event. That is
  what makes commands testable without a GUI, and scriptable later.
- **The ezdxf document is the model.** There is no shadow data structure. What
  IngeCAD does not understand about a drawing (proxies, XDATA, dictionaries,
  3DSOLID) must survive a round trip untouched.
- New behaviour comes with a test. A test that passes with the bug still in
  place proves nothing — check that it fails when you revert your fix.

## Translating IngeCAD

**Everything you read is translatable; everything you type is English.**

IngeCAD exists so that an AutoCAD user can type what their fingers already
know — `L`, `TR`, `Z` — and have it work. So the command line is English in
every language of the interface. Menus, dialogs, panels and the *text* of
prompts are translated; command names and the option keys inside prompts are
not.

That gives translations one hard rule. A prompt like

```
Specify rotation angle or [Reference]:
```

is parsed against the English key `R`, so the translation has to keep that key
where the user can see it:

```json
"Specify rotation angle or [Reference]:":
    "Especifique el ángulo de rotación o [Referencia(R)]:"
```

Three spellings are accepted, all of them AutoCAD's own: the key in
parentheses — `Suprimir(D)`; the capitals of the word carrying it —
`CEntro` for `CE`; or the keyword left untranslated — `3P`, `Ttr`. Options are
matched in order, so keep them in the order the English string uses.
`tests/test_i18n_prompt_keys.py` enforces this on every language file.

### Adding your language

A language is a **folder**, and adding one needs no Python at all:

```
i18n/
  es/  meta.json  ui.json
  cs/  meta.json  ui.json     <- yours
```

`meta.json` names it in the menu:

```json
{ "code": "cs", "name": "Čeština", "maintainer": "you <you@example.org>" }
```

`name` is the language's own name, so the menu stays readable whichever
language is active. Leave `maintained` out — that flag marks the languages
this project itself keeps complete, and it makes CI fail when they fall
behind.

`ui.json` is the flat `{english: translation}` map; copy `i18n/es/ui.json` as
a model, since it shows the bracket convention in use.

**Partial is fine**: a missing key falls back to the English source string, so
an incomplete file degrades to readable English rather than to a broken key,
and no release is ever blocked on a translation. You own your file — nobody
else will silently rewrite it.

The **old flat layout** (`i18n/<code>.json`) still loads, so a translation
written before the folders keeps working; it just shows its code instead of
its name in the menu until it is converted.

### Command names in your language (optional)

A localized AutoCAD takes `LINEA` and `BORRA`, and so can IngeCAD — add
`commands.json` to your folder:

```json
{ "LINE": {"name": "LINEA"}, "ERASE": {"name": "BORRA"} }
```

**English never stops working**: `L`, `LINE` and `_LINE` all draw a line
whatever the interface language, and `_` is AutoCAD's global prefix for
exactly that reason. So a pack may only *add* names. Naming a command that
does not exist, claiming a token English already answers to, or giving one
token to two commands is refused — `tests/test_i18n_commands.py` walks the
whole alias table under every installed language to prove it.

Aliases (`"aliases": ["BO"]`) are supported and rarely worth it: the English
one-letter aliases are the muscle memory the product is built on, so almost
every short one is already taken and would be refused.

The full picture, including where the language machinery is going, is in
[`docs/i18n.md`](docs/i18n.md).
