# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

OpenCoder is a desktop app (PySide6/Qt) for qualitative data analysis: importing text documents, tagging ("coding") spans of text with a hierarchical codebook, and exporting/reporting on the coded segments. Projects are single `.sqlite` files.

## Commands

```bash
pip install -e ".[dev]"        # install package + dev deps (pytest, pytest-qt)
python -m opencoder             # run the app (or the `opencoder` console script)
pytest                          # run the full test suite
pytest tests/test_db.py::test_create_code_and_list_codes   # run a single test
```

There is no configured linter/formatter/type-checker in `pyproject.toml` — don't assume `ruff`/`black`/`mypy` are wired in.

## Architecture

**Layering:** `db.py` → `reporting.py` → `ui/*`. The bottom two have zero Qt imports and operate directly on a `sqlite3.Connection`, so they're usable from tests (or a future CLI) without spinning up a `QApplication`.

- **`db.py`** — the only place that touches SQL. Three tables: `documents`, `codes` (self-referencing via `parent_id`, `ON DELETE CASCADE`), `segments` (document + code + `start_offset`/`end_offset` char range + optional memo). Note `delete_code` re-parents a deleted code's children to its own parent *before* deleting, specifically to dodge the cascade that would otherwise wipe out the whole subtree.
- **`reporting.py`** — read-only aggregation/export over `db.py` (CSV/JSON segment export, code-frequency counts). `code_path()` builds the "Parent > Child" breadcrumb by walking `parent_id` up to the root.
- **`ui/main_window.py`** — the app. `MainWindow` methods split into two groups by convention: `_on_*` slots that own dialog/QMessageBox interaction, and plain methods (`create_project`, `import_document`, `add_code`, `apply_segment`, `delete_code`, ...) that contain the actual logic and take/return plain values. Tests drive the app through the latter, never through the `_on_*` slots or real file dialogs.
- **`ui/vim_viewer.py`** — `VimTextViewer`, a read-only `QPlainTextEdit` with hand-rolled vim motions (`hjkl`, `w/b/e` vs `W/B/E` WORD variants, `0/$`, `gg/G`, viewport-relative `H/L`, visual mode via `v`). It disables the native blinking cursor (`setCursorWidth(0)`) and instead renders its own block-cursor highlight as an `ExtraSelection`, layered alongside the per-code highlight selections from `MainWindow`.
- **`ui/code_tree.py`** — `CodeTreeWidget`, adds internal drag-and-drop re-parenting on top of `QTreeWidget`, emitting `codeReparented(code_id, new_parent_id)` for `MainWindow` to persist (and validate — no self-parenting, no moving under one's own descendant).
- **`ui/code_filter_input.py`** — `CodeFilterLineEdit`, a `QLineEdit` that repurposes Up/Down to cycle the currently-matched code instead of moving the text cursor.
- **`ui/report_dialog.py`** — plain read-only table dialog for the code-frequency report.

**Cross-pane keyboard model:** `MainWindow` installs a `QApplication`-wide `eventFilter` (not per-widget handlers) so a handful of shortcuts work regardless of which pane has focus: Space jumps focus to the code filter, Up/Down cycle the matched/highlighted code when the viewer has a selection, Enter applies the current code to the viewer's selection, and `x` deletes segments touching the cursor (normal mode) or the current selection (visual mode). When adding a new global shortcut, it goes here, not on an individual widget.

**Focus styling:** panes are visually highlighted on focus via a Qt dynamic property (`"focused"`) toggled from `QApplication.focusChanged`, matched by the QSS in `PANE_FOCUS_STYLE` — not via per-widget `focusInEvent` overrides.

**Coding workflow invariant:** applying a code always goes through `MainWindow.apply_segment`, which both writes the segment (`db.create_segment`) and refreshes the code tree/highlights/segment list in one place — don't call `db.create_segment` directly from UI code.
