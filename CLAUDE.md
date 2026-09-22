# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

OpenAnsho is a desktop app (PySide6/Qt) for qualitative data analysis: importing text documents, tagging ("coding") spans of text with a hierarchical codebook, and exporting/reporting on the coded segments. Projects are single `.sqlite` files.

## Development setup

First-time setup, run once from the repo root:

```bash
python3 -m venv .venv           # create the project virtualenv
source .venv/bin/activate       # activate it
pip install -e ".[dev]"        # install package + dev deps (pytest, pytest-qt)
```

Every subsequent session, activate the virtualenv before running any commands below:

```bash
source .venv/bin/activate       # activate the project virtualenv
```

To run the development version of the app (with the virtualenv active):

```bash
python -m openansho              # run the app (or the `openansho` console script)
```

## Commands

The project uses a `.venv` virtualenv at the repo root — activate it before running any of the commands below.

```bash
source .venv/bin/activate       # activate the project virtualenv
pip install -e ".[dev]"        # install package + dev deps (pytest, pytest-qt)
python -m openansho             # run the app (or the `openansho` console script)
pytest                          # run the full test suite
pytest tests/test_db.py::test_create_code_and_list_codes   # run a single test
make dist                       # build the PyPI sdist + wheel into dist/pypi
```

There is no configured linter/formatter/type-checker in `pyproject.toml` — don't assume `ruff`/`black`/`mypy` are wired in.

**Known hang: the full suite in Claude Code's sandbox.** Running the unscoped suite (bare `pytest`, or `pytest tests/`) reliably hangs in Claude Code's sandboxed/offscreen environment — the process gets stuck in an uninterruptible sleep that not even `kill -9` can clear, apparently a Qt/native-windowing issue with `tests/test_always_selected_code.py` specifically when it runs alongside the rest of the suite (it passes in well under a second in isolation, e.g. `pytest tests/test_always_selected_code.py`). `pytest tests/ --ignore=tests/test_always_selected_code.py` runs the rest of the suite (142 tests) in about a second. Claude Code should scope test runs (a single file, `--ignore` that file, or `-k`) rather than invoking the bare full suite. The human developer should still run the full suite occasionally outside this sandbox (a normal local terminal), since that's the only way to catch a regression in the one file this workaround always excludes.

## Distribution

The app ships through two channels, and a change to how the app finds its files has to work in both:

- **Prebuilt executables** via PyInstaller (`make build-mac`/`build-windows`/`build-linux`, published to the `builds` branch by `.github/workflows/ci.yml`).
- **A PyPI sdist + wheel** (`make dist`, published by `.github/workflows/release.yml` on a `v*` tag via trusted publishing; `make publish` is the manual fallback). Releasing means bumping `__version__` in `src/openansho/__init__.py` — hatchling reads the version from there, so `pyproject.toml` has none of its own — then pushing a matching tag, which the workflow verifies against `__version__` before uploading.

Consequences worth knowing before touching the packaging:

- **`__main__._icon_path` has three branches** because the icon lives in a different place in each layout: `sys._MEIPASS/images/` in a PyInstaller bundle, next to the package in an installed wheel (pyproject `force-include`s `images/kanji_shou_app_icon.png` into `openansho/`, since a wheel has no repo root), and `images/` at the repo root when running from source. Package data added in the future needs the same treatment — `tutorial.txt` avoids it by living inside the package to begin with, which is the simpler option.
- **`user.username_file` picks a directory based on how the app was installed.** Frozen builds and source checkouts own their directory, so the `.openansho_user` sidecar sits next to the app as before; a pip install would otherwise write into site-packages, which can be read-only and is replaced wholesale on upgrade, so `user.installed_in_site_packages()` routes it to `user.config_directory()` instead.
- **The entry point is a `gui-script`, not a `console script`**, so the Windows launcher is built against `pythonw` and doesn't leave a console window behind the app. `python -m openansho` is the console-attached form to recommend when someone needs a traceback.
- `tests/test_packaging.py` covers the layout-dependent paths; `tests/conftest.py` pins `installed_in_site_packages` off so the suite never touches a real config directory.

## Architecture

**Layering:** `db.py` → `reporting.py`/`text_extract.py`/`tutorial.py` → `ui/*`. The non-UI modules have zero Qt imports and operate directly on a `sqlite3.Connection`, so they're usable from tests (or a future CLI) without spinning up a `QApplication`.

- **`db.py`** — the only place that touches SQL. Three tables: `documents`, `codes` (self-referencing via `parent_id`, `ON DELETE CASCADE`), `segments` (document + code + `start_offset`/`end_offset` char range + optional memo). Note `delete_code` re-parents a deleted code's children to its own parent *before* deleting, specifically to dodge the cascade that would otherwise wipe out the whole subtree.
- **`reporting.py`** — read-only aggregation/export over `db.py` (CSV/JSON segment export, code-frequency counts). `code_path()` builds the "Parent > Child" breadcrumb by walking `parent_id` up to the root.
- **`text_extract.py`** — `read_document_text(path)` turns a file into the plain text that gets stored in `documents.content`, dispatching on extension: `.docx` goes through a hand-rolled `zipfile`+`ElementTree` reader (no `python-docx`, so the packaged app keeps PySide6 as its only dependency), anything else is read as UTF-8. Failures raise `DocumentReadError` whose message is shown verbatim in the import dialog.
- **`tutorial.py`** — the built-in tutorial project the app opens at startup (`__main__.main` calls `MainWindow.open_tutorial_project`, also reachable via File > Open Tutorial). `open_tutorial_project()` returns a `db.connect(":memory:")` connection seeded with `tutorial.txt`, which ships as package data next to the module — the in-memory database is the whole mechanism for "the tutorial codebook is never saved," so don't give it a file path. `MainWindow._set_connection` accepts `path=None` for exactly this project: no file to title the window after and nothing to put in Open Recent.
- **`ui/main_window.py`** — the app. `MainWindow` methods split into two groups by convention: `_on_*` slots that own dialog/QMessageBox interaction, and plain methods (`create_project`, `import_document`, `add_code`, `apply_segment`, `delete_code`, ...) that contain the actual logic and take/return plain values. Tests drive the app through the latter, never through the `_on_*` slots or real file dialogs.
- **`ui/vim_viewer.py`** — `VimTextViewer`, a read-only `QPlainTextEdit` with hand-rolled vim motions (`hjkl`, `w/b/e` vs `W/B/E` WORD variants, `0/$`, `gg/G`, viewport-relative `H/L`, visual mode via `v`). It disables the native blinking cursor (`setCursorWidth(0)`) and instead renders its own block-cursor highlight as an `ExtraSelection`, layered alongside the per-code highlight selections from `MainWindow`.
- **`ui/code_tree.py`** — `CodeTreeWidget`, adds internal drag-and-drop re-parenting on top of `QTreeWidget`, emitting `codeReparented(code_id, new_parent_id)` for `MainWindow` to persist (and validate — no self-parenting, no moving under one's own descendant).
- **`ui/code_filter_input.py`** — `CodeFilterLineEdit`, a `QLineEdit` that repurposes Up/Down to cycle the currently-matched code instead of moving the text cursor.
- **`ui/report_dialog.py`** — plain read-only table dialog for the code-frequency report.
- **`ui/font_scale.py`** — application-wide font scaling, expressed as a percentage of the platform's default UI font. Scaling has to be applied *twice* to actually take effect: `apply_font_scale` sets `QApplication`'s font (what later-created dialogs/menus start from), and `font_scale_style` returns a `QWidget { font-size: … }` fragment that `MainWindow._apply_theme` appends to the theme stylesheet — setting any stylesheet makes Qt give each polished widget an explicit font, which then stops tracking `QApplication`'s, so already-built panes only resize via the stylesheet. Note Qt's QSS parser silently rejects fractional point sizes, hence the rounding in `scaled_font`.

**Cross-pane keyboard model:** `MainWindow` installs a `QApplication`-wide `eventFilter` (not per-widget handlers) so a handful of shortcuts work regardless of which pane has focus: Space jumps focus to the code filter, Up/Down cycle the matched/highlighted code when the viewer has a selection, Enter applies the current code to the viewer's selection, and `x` deletes segments touching the cursor (normal mode) or the current selection (visual mode). When adding a new global shortcut, it goes here, not on an individual widget.

**Focus styling:** panes are visually highlighted on focus via a Qt dynamic property (`"focused"`) toggled from `QApplication.focusChanged`, matched by the QSS in `PANE_FOCUS_STYLE` — not via per-widget `focusInEvent` overrides.

**Coding workflow invariant:** applying a code always goes through `MainWindow.apply_segment`, which both writes the segment (`db.create_segment`) and refreshes the code tree/highlights/segment list in one place — don't call `db.create_segment` directly from UI code.

**Keyboard shortcuts must stay documented.** `ui/shortcuts_dialog.py`'s `SHORTCUT_SECTIONS` is shown to the user via the `?` popup and is the single source of truth for "what keys does this app respond to." Any time a keyboard shortcut is added, changed, or removed anywhere in the UI (the global `eventFilter` in `main_window.py`, vim motions in `vim_viewer.py`, `code_filter_input.py`, `code_tree.py`, or any `QShortcut`/menu accelerator), update `SHORTCUT_SECTIONS` in the same change so the popup never drifts out of sync with actual behavior.
