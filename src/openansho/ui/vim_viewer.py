from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QPlainTextEdit, QTextEdit

from openansho.ui.highlight_paint import paint_diagonal_stripes
from openansho.ui.vim_keys import VimTextNavigation

STRIPE_WIDTH_IN_CHARS = 2

CONFLICT_OUTLINE_COLOR = QColor("red")
CONFLICT_OUTLINE_WIDTH = 2


@dataclass(frozen=True)
class CodeHighlight:
    """One coded span to paint, plus its vertical band among selected users.

    `band_index`/`band_count` divide the highlighted line height into
    `band_count` equal horizontal stripes and pick stripe `band_index`
    (0 = top), so segments from different users stack instead of
    overlapping when more than one user is selected.

    `outlined` marks a segment that overlaps another selected segment
    coded with a different code, so its band gets a red border.

    `stripe_colors`, when set (2+ entries), means multiple codes share this
    exact span; the band is painted as alternating diagonal stripes cycling
    through every color instead of a solid fill of `color`.
    """

    start: int
    end: int
    color: QColor
    band_index: int
    band_count: int
    outlined: bool = False
    stripe_colors: tuple[QColor, ...] | None = None


class VimTextViewer(VimTextNavigation, QPlainTextEdit):
    """A read-only text viewer navigable with vim-style keybindings.

    The keybindings themselves — the modes, the motions and the search —
    live in `vim_keys.VimTextNavigation`, shared with the PDF pane. What is
    here is everything that depends on this being a plain-text widget: the
    viewport-relative motions (H/L/M, zz/zt/zb, Ctrl+E/Ctrl+Y) measured in
    document blocks, the painting of coded spans and of the block cursor,
    and insert mode.

    It disables the native blinking cursor (`setCursorWidth(0)`) and renders
    its own block-cursor highlight as an `ExtraSelection`, layered alongside
    the per-code highlight selections from `MainWindow` — except in insert
    mode, which swaps back to a real blinking I-beam and makes the widget
    writable. Every edit made while in insert mode is reported via
    `contentEdited` (position, charsRemoved, charsAdded) so a listener can
    shift or truncate coded segments' offsets to match; programmatic content
    changes (`setPlainText`/`clear`/`replace_text`) are not reported, since
    those aren't edits to reconcile offsets against.
    """

    modeChanged = Signal(str)
    searchTextChanged = Signal(str)
    contentEdited = Signal(int, int, int)  # position, charsRemoved, charsAdded

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setCursorWidth(0)  # we render our own block cursor instead

        self._init_vim_state()
        self._code_highlights: list[CodeHighlight] = []
        self._suspend_edit_tracking = False

        self.set_theme(dark_mode=False)

        self.cursorPositionChanged.connect(self._refresh_extra_selections)
        self.document().contentsChange.connect(self._on_contents_change)
        self._refresh_extra_selections()

    def setPlainText(self, text: str) -> None:
        """Load `text` without reporting it through `contentEdited`.

        Used to load a different document's content, which isn't an edit
        that existing segment offsets need to be reconciled against.
        """
        self._suspend_edit_tracking = True
        try:
            super().setPlainText(text)
        finally:
            self._suspend_edit_tracking = False

    def clear(self) -> None:
        self._suspend_edit_tracking = True
        try:
            super().clear()
        finally:
            self._suspend_edit_tracking = False

    def replace_text(self, position: int, length: int, text: str) -> None:
        """Splice `text` in over `length` characters at `position`.

        Not reported through `contentEdited`, unlike a user's insert-mode
        edit: this is for edits the caller is reconciling the database
        against itself with offsets it already knows (the PDF region
        markers in `MainWindow.create_region`/`delete_region`). Editing in
        place rather than reloading the whole document keeps the viewer's
        scroll position.
        """
        cursor = QTextCursor(self.document())
        cursor.setPosition(position)
        if length:
            cursor.setPosition(position + length, QTextCursor.KeepAnchor)
        self._suspend_edit_tracking = True
        try:
            cursor.insertText(text)  # replaces the selection, if any
        finally:
            self._suspend_edit_tracking = False


    def _on_insert_mode_changed(self, entering: bool) -> None:
        """Swap the hand-rolled block cursor for a real one, and allow editing."""
        self.setReadOnly(not entering)
        self.setCursorWidth(1 if entering else 0)
        self._refresh_extra_selections()

    def _on_contents_change(self, position: int, chars_removed: int, chars_added: int) -> None:
        if self._suspend_edit_tracking:
            return
        self.contentEdited.emit(position, chars_removed, chars_added)

    def set_theme(self, dark_mode: bool) -> None:
        """Set the block cursor colors for the given theme.

        Should read as inverted relative to the surrounding pane, so the
        cursor stays visible against either a black (dark mode) or white
        (light mode) background.

        Visual-mode selection color is set via QSS (`selection-background-color`/
        `selection-color` on #viewerPane in main_window.py), not QPalette here:
        a QPalette::Highlight set before the widget's first show gets silently
        discarded by the stylesheet's first polish pass, which otherwise
        defaults the native selection to the same colors as ordinary text —
        making visual-mode selections invisible.
        """
        if dark_mode:
            self._cursor_bg = QColor(255, 255, 255)
            self._cursor_fg = QColor(0, 0, 0)
        else:
            self._cursor_bg = QColor(0, 0, 0)
            self._cursor_fg = QColor(255, 255, 255)

        self._refresh_extra_selections()

    def set_code_highlights(self, highlights: list[CodeHighlight]) -> None:
        self._code_highlights = list(highlights)
        self.viewport().update()

    def _visible_line_starts(self) -> list[int]:
        """Character positions of the first character of each line currently visible in the viewport."""
        viewport_bottom = self.viewport().rect().bottom()
        starts = []
        block = self.firstVisibleBlock()
        while block.isValid():
            top = self.blockBoundingGeometry(block).translated(self.contentOffset()).top()
            if top > viewport_bottom:
                break
            starts.append(block.position())
            block = block.next()
        return starts

    
    def _scroll_current_line_to_top(self) -> None:
        """Handle zt: scroll the viewport so the cursor's line is at the top, without moving the cursor."""
        self.verticalScrollBar().setValue(self.textCursor().blockNumber())

    def _scroll_current_line_to_bottom(self) -> None:
        """Handle zb: scroll the viewport so the cursor's line is at the bottom, without moving the cursor."""
        block_number = self.textCursor().blockNumber()
        line_height = max(self.fontMetrics().height(), 1)
        visible_lines = max(self.viewport().height() // line_height, 1)
        self.verticalScrollBar().setValue(max(block_number - visible_lines + 1, 0))

    def _scroll_viewport_lines(self, delta: int) -> None:
        """Handle Ctrl+E/Ctrl+Y: scroll the viewport by one line without moving the cursor."""
        scrollbar = self.verticalScrollBar()
        scrollbar.setValue(scrollbar.value() + delta)

    

    def paintEvent(self, event) -> None:
        painter = QPainter(self.viewport())
        for highlight in self._code_highlights:
            self._paint_code_highlight(painter, highlight)
        painter.end()
        super().paintEvent(event)

    def _paint_code_highlight(self, painter: QPainter, highlight: CodeHighlight) -> None:
        for rect in self._line_rects_for_range(highlight.start, highlight.end):
            band_height = rect.height() / highlight.band_count
            band_top = rect.top() + highlight.band_index * band_height
            band_rect = QRectF(rect.left(), band_top, rect.width(), band_height)

            if highlight.stripe_colors:
                self._paint_diagonal_stripes(painter, band_rect, highlight.stripe_colors)
            else:
                painter.fillRect(band_rect, highlight.color)
            if highlight.outlined:
                # Outline the full coded-text rect (not the smaller per-user
                # band) so the border marks the original text, not just this
                # user's stripe of it.
                pen = QPen(CONFLICT_OUTLINE_COLOR)
                pen.setWidth(CONFLICT_OUTLINE_WIDTH)
                painter.setPen(pen)
                painter.drawRect(rect)
                painter.setPen(Qt.NoPen)

    def _paint_diagonal_stripes(
        self, painter: QPainter, rect: QRectF, colors: tuple[QColor, ...]
    ) -> None:
        """Stripe `rect` through `colors`, each stripe roughly two characters wide."""
        paint_diagonal_stripes(
            painter,
            rect,
            colors,
            self.fontMetrics().averageCharWidth() * STRIPE_WIDTH_IN_CHARS,
        )

    def _line_rects_for_range(self, start: int, end: int) -> list[QRect]:
        """Viewport rects covering [start, end), one per visual line it spans.

        Mirrors what a full-height ExtraSelection would cover, so callers
        can subdivide each line's rect into per-user bands. Uses
        `cursorRect()` (viewport coordinates) rather than QTextLayout
        internals so soft-wrapped lines are handled the same as hard
        paragraph breaks.
        """
        if end <= start:
            return []

        doc = self.document()
        rects = []
        pos = start
        while pos < end:
            line_end_cursor = QTextCursor(doc)
            line_end_cursor.setPosition(pos)
            line_end_cursor.movePosition(QTextCursor.EndOfLine)
            hit_block_end = line_end_cursor.atBlockEnd()
            line_end_pos = min(line_end_cursor.position(), end)

            left_cursor = QTextCursor(doc)
            left_cursor.setPosition(pos)
            right_cursor = QTextCursor(doc)
            right_cursor.setPosition(line_end_pos)

            left_rect = self.cursorRect(left_cursor)
            right_rect = self.cursorRect(right_cursor)
            left = min(left_rect.left(), right_rect.left())
            right = max(left_rect.left(), right_rect.left())
            if right <= left:
                right = left + 1
            rects.append(QRect(left, left_rect.top(), right - left, left_rect.height()))

            if line_end_pos >= end:
                break
            next_pos = line_end_pos + 1 if hit_block_end else line_end_pos
            pos = next_pos if next_pos > pos else pos + 1
        return rects

    def _refresh_extra_selections(self) -> None:
        if self.mode == self.INSERT:
            # A normal blinking cursor is visible instead; no block to highlight.
            super().setExtraSelections([])
            return
        super().setExtraSelections([self._cursor_highlight_selection()])

    def _cursor_highlight_selection(self) -> QTextEdit.ExtraSelection:
        block_cursor = QTextCursor(self.textCursor())
        block_cursor.clearSelection()
        if block_cursor.atEnd():
            # No character to highlight ahead of the cursor; fall back to the
            # character behind it so the block cursor stays visible at the
            # very end of the document instead of disappearing.
            if not block_cursor.atStart():
                block_cursor.movePosition(QTextCursor.PreviousCharacter, QTextCursor.KeepAnchor)
        else:
            block_cursor.movePosition(QTextCursor.NextCharacter, QTextCursor.KeepAnchor)

        fmt = QTextCharFormat()
        fmt.setBackground(self._cursor_bg)
        fmt.setForeground(self._cursor_fg)

        selection = QTextEdit.ExtraSelection()
        selection.cursor = block_cursor
        selection.format = fmt
        return selection
