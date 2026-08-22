# Contributing to IngeCAD

Patches, bug reports and translations are welcome. IngeCAD is
GPL-3.0-or-later; by contributing you agree your work ships under that
licence. Contributors are listed in `AUTHORS`.

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

To add a language, copy `i18n/es.json` as a model and translate what you can.
**Partial is fine**: a missing key falls back to the English source string, so
an incomplete file degrades to readable English rather than to a broken key,
and no release is ever blocked on a translation. You own your file — nobody
else will silently rewrite it.

The full picture, including where the language machinery is going, is in
[`docs/i18n.md`](docs/i18n.md).
