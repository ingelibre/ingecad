<!--
Thank you. Nothing here is bureaucracy: each line exists because it saves a
round trip. Delete what does not apply, and write in English or Spanish.
-->

## What this changes, and why

<!-- The problem first, the fix second. If it closes an issue: "Closes #12". -->

## How it was verified

<!--
Not "tests pass" -- what you actually checked. For this project that usually
means one of:

  - a new test that fails without the change (the surest kind);
  - a real drawing, named, before and after;
  - a measurement: entity counts, pixels, milliseconds.

A test that passes proves nothing if it would also pass with the bug in place.
-->

## Checklist

- [ ] `venv/bin/python -m pytest` is green
- [ ] New behaviour comes with a test, and I checked it fails without the fix
- [ ] Code, comments and commit messages are in English (see CONTRIBUTING.md)
- [ ] If it touches the interface: the strings go through `tr()`
- [ ] If it touches a translated prompt: the English key stays in the brackets,
      `[Suprimir(D)]` (see `docs/i18n.md`)
