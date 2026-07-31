from __future__ import annotations

import re
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QPlainTextEdit, QTextEdit

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


class VimTextViewer(QPlainTextEdit):
    """A read-only text viewer navigable with vim-style keybindings.

    Normal mode moves a visible block cursor with h/j/k/l, w/b/e, 0/$, gg/G.
    Pressing v enters visual mode, where the same motions extend a text
    selection instead of just moving the cursor. Shift+W/B/E are vim's
    "WORD" variants: they treat any run of non-blank characters as a
    single unit, so punctuation around or inside a word never stops them
    (unlike lowercase w/b/e, which treat punctuation as its own word).

    G/gg jump to the bottom/top of the whole document. Shift+H/L/M are
    viewport-relative instead: H jumps to the start of the first line
    currently visible in the viewport, L to the start of the last one,
    M to the start of the middle one. zz scrolls the viewport so the
    current cursor line is centered, zt scrolls it to the top, and zb
    scrolls it to the bottom, all without moving the cursor itself.
    Ctrl+E/Ctrl+Y scroll the viewport down/up by one line, also without
    moving the cursor.

    f followed by any character jumps forward to the next occurrence of
    that character anywhere in the document (case-sensitive), crossing
    line boundaries freely. Shift+F does the same searching backward.

    Pressing / enters search mode: typed characters are interpreted as a
    Python regular expression and the cursor progressively jumps to the
    first match at or after the position search started from, updating
    live as the pattern changes. Matching is smartcase: an all-lowercase
    pattern matches either case, but any uppercase letter in it makes the
    match case-sensitive. Enter commits the pattern (leaving the cursor
    on the match, never applying a code) and Escape cancels, restoring
    the original cursor position. Once a pattern has been committed, n
    repeats the search forward from the cursor and Shift+N repeats it
    backward; both switch to visual mode with the whole match selected,
    ready to code it with Enter.

    Pressing i from normal mode enters insert mode, which re-enables
    ordinary text editing (the widget is otherwise read-only) and swaps
    the hand-rolled block cursor for a normal blinking I-beam one. Escape
    returns to normal mode. Every edit made while in insert mode is
    reported via `contentEdited` (position, charsRemoved, charsAdded) so
    a listener can shift or truncate coded segments' offsets to match;
    programmatic content changes (`setPlainText`/`clear`, used when
    loading a different document) are not reported, since those aren't
    edits to reconcile offsets against.
    """

    NORMAL = "normal"
    VISUAL = "visual"
    SEARCH = "search"
    INSERT = "insert"

    modeChanged = Signal(str)
    searchTextChanged = Signal(str)
    contentEdited = Signal(int, int, int)  # position, charsRemoved, charsAdded

    # Keyed by key code (not text) so Shift-based case doesn't matter here;
    # shifted letters (W/B/E, G) are disambiguated via the Shift modifier.
    #
    # j/k and 0/$ are deliberately *not* here: Qt's QTextCursor.Down/Up and
    # Start/EndOfLine move by visual (soft-wrapped) line, but vim's plain
    # j/k/0/$ move by logical line regardless of wrapping (that's what
    # gj/gk are for in real vim) — see _move_down_line/_move_up_line/
    # _move_to_line_start/_move_to_line_end. Using the visual-line ops here
    # made these motions' behavior depend on widget width and font metrics,
    # which differed enough across platforms to flip test outcomes in CI.
    _MOTION_KEYS = {
        Qt.Key_Left: QTextCursor.Left,  # alias, doesn't conflict with code-cycling (Up/Down only)
        Qt.Key_Right: QTextCursor.Right,
    }

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setCursorWidth(0)  # we render our own block cursor instead

        self.mode = self.NORMAL
        self._pending_g = False
        self._pending_z = False
        self._pending_find: int | None = None
        self._code_highlights: list[CodeHighlight] = []
        self._search_pattern = ""
        self._search_buffer = ""
        self._search_origin = 0
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

    @property
    def awaiting_find_char(self) -> bool:
        """True right after f/F, while the next keypress is still owed as its target char."""
        return self._pending_find is not None

    def exit_visual_mode(self) -> None:
        if self.mode != self.VISUAL:
            return
        self.mode = self.NORMAL
        cursor = self.textCursor()
        cursor.clearSelection()
        self.setTextCursor(cursor)
        self.modeChanged.emit(self.mode)

    def enter_insert_mode(self) -> None:
        if self.mode == self.INSERT:
            return
        if self.mode == self.SEARCH:
            self._cancel_search()
        self.mode = self.INSERT
        self.setReadOnly(False)
        self.setCursorWidth(1)  # ordinary blinking I-beam, not the vim block cursor
        self._refresh_extra_selections()
        self.modeChanged.emit(self.mode)

    def exit_insert_mode(self) -> None:
        if self.mode != self.INSERT:
            return
        self.mode = self.NORMAL
        self.setReadOnly(True)
        self.setCursorWidth(0)  # back to rendering our own block cursor
        self._refresh_extra_selections()
        self.modeChanged.emit(self.mode)

    def keyPressEvent(self, event) -> None:
        if self.mode == self.SEARCH:
            self._handle_search_key(event)
            return

        if self.mode == self.INSERT:
            if event.key() == Qt.Key_Escape:
                self.exit_insert_mode()
                event.accept()
                return
            super().keyPressEvent(event)
            return

        key = event.key()
        text = event.text()
        shift = bool(event.modifiers() & Qt.ShiftModifier)

        if self._pending_find is not None:
            if key in (Qt.Key_Shift, Qt.Key_Control, Qt.Key_Alt, Qt.Key_Meta):
                # A bare modifier press (e.g. Shift held down before "W" arrives)
                # is delivered as its own keypress first; it must not consume
                # the pending f/F state before the actual target character.
                event.accept()
                return
            direction = self._pending_find
            self._pending_find = None
            if key != Qt.Key_Escape and text:
                self._find_char(text, direction)
            event.accept()
            return

        if key == Qt.Key_Escape:
            self._pending_g = False
            self._pending_z = False
            self.exit_visual_mode()
            event.accept()
            return

        if key == Qt.Key_V:
            self._pending_g = False
            self._pending_z = False
            self._toggle_visual_mode()
            event.accept()
            return

        if key == Qt.Key_I:
            if self.mode == self.NORMAL:
                self._pending_g = False
                self._pending_z = False
                self.enter_insert_mode()
            event.accept()
            return

        if key == Qt.Key_G:
            self._pending_z = False
            if shift:
                self._pending_g = False
                self._move(QTextCursor.End)
            elif self._pending_g:
                self._pending_g = False
                self._move(QTextCursor.Start)
            else:
                self._pending_g = True
            event.accept()
            return

        if key == Qt.Key_Z and not shift:
            self._pending_g = False
            if self._pending_z:
                self._pending_z = False
                self.centerCursor()
            else:
                self._pending_z = True
            event.accept()
            return

        if self._pending_z and key in (Qt.Key_T, Qt.Key_B) and not shift:
            self._pending_z = False
            if key == Qt.Key_T:
                self._scroll_current_line_to_top()
            else:
                self._scroll_current_line_to_bottom()
            event.accept()
            return

        self._pending_g = False
        self._pending_z = False

        if key == Qt.Key_E and event.modifiers() & Qt.ControlModifier:
            self._scroll_viewport_lines(1)
            event.accept()
            return

        if key == Qt.Key_Y and event.modifiers() & Qt.ControlModifier:
            self._scroll_viewport_lines(-1)
            event.accept()
            return

        if key == Qt.Key_H:
            if shift:
                self._jump_to_first_visible_line()
            else:
                self._move(QTextCursor.Left)
            event.accept()
            return

        if key == Qt.Key_L:
            if shift:
                self._jump_to_last_visible_line()
            else:
                self._move(QTextCursor.Right)
            event.accept()
            return

        if key == Qt.Key_M and shift:
            self._jump_to_middle_visible_line()
            event.accept()
            return

        if key == Qt.Key_E:
            self._move_to_word_end(self._is_big_word_char if shift else self._is_word_char)
            event.accept()
            return

        if key == Qt.Key_W:
            if shift:
                self._move_to_next_word_start(self._is_big_word_char)
            else:
                self._move(QTextCursor.NextWord)
            event.accept()
            return

        if key == Qt.Key_B:
            if shift:
                self._move_to_previous_word_start(self._is_big_word_char)
            else:
                self._move(QTextCursor.PreviousWord)
            event.accept()
            return

        if key == Qt.Key_Slash:
            self._enter_search_mode()
            event.accept()
            return

        if key == Qt.Key_N:
            self._jump_to_search_match(-1 if shift else 1)
            event.accept()
            return

        if key == Qt.Key_F:
            self._pending_find = -1 if shift else 1
            event.accept()
            return

        if key == Qt.Key_J:
            self._move_down_line()
            event.accept()
            return

        if key == Qt.Key_K:
            self._move_up_line()
            event.accept()
            return

        if key == Qt.Key_Dollar:
            self._move_to_line_end()
            event.accept()
            return

        if text == "0":
            self._move_to_line_start()
            event.accept()
            return

        operation = self._MOTION_KEYS.get(key)
        if operation is not None:
            self._move(operation)
            event.accept()
            return

        event.ignore()

    def _toggle_visual_mode(self) -> None:
        if self.mode == self.VISUAL:
            self.exit_visual_mode()
        else:
            self._enter_visual_mode()

    def _enter_visual_mode(self) -> None:
        if self.mode != self.VISUAL:
            self.mode = self.VISUAL
            self.modeChanged.emit(self.mode)

    def _enter_search_mode(self) -> None:
        self.mode = self.SEARCH
        self._search_buffer = ""
        self._search_origin = self.textCursor().position()
        self.modeChanged.emit(self.mode)

    def _handle_search_key(self, event) -> None:
        key = event.key()
        if key == Qt.Key_Escape:
            self._cancel_search()
            event.accept()
            return
        if key in (Qt.Key_Return, Qt.Key_Enter):
            self._commit_search()
            event.accept()
            return
        if key == Qt.Key_Backspace:
            self._search_buffer = self._search_buffer[:-1]
            self._update_search_preview()
            event.accept()
            return

        text = event.text()
        if text and text.isprintable():
            self._search_buffer += text
            self._update_search_preview()
        event.accept()

    def _update_search_preview(self) -> None:
        self.searchTextChanged.emit(self._search_buffer)
        regex = self._compile_search_pattern(self._search_buffer)
        match = self._find_match(regex, self._search_origin, forward=True) if regex else None
        if match is not None:
            self._select_match(match)
        else:
            cursor = self.textCursor()
            cursor.setPosition(self._search_origin)
            self.setTextCursor(cursor)

    def _commit_search(self) -> None:
        regex = self._compile_search_pattern(self._search_buffer)
        if regex is not None:
            self._search_pattern = self._search_buffer
            match = self._find_match(regex, self._search_origin, forward=True)
            if match is not None:
                cursor = self.textCursor()
                cursor.setPosition(match.start())
                self.setTextCursor(cursor)
                self.ensureCursorVisible()
        # Re-emit the actually-committed pattern, discarding an empty or
        # invalid-regex draft rather than leaving it displayed as if saved.
        self.searchTextChanged.emit(self._search_pattern)
        self._exit_search_mode()

    def _cancel_search(self) -> None:
        cursor = self.textCursor()
        cursor.setPosition(self._search_origin)
        self.setTextCursor(cursor)
        self.searchTextChanged.emit(self._search_pattern)
        self._exit_search_mode()

    def _exit_search_mode(self) -> None:
        self.mode = self.NORMAL
        self._search_buffer = ""
        self.modeChanged.emit(self.mode)

    def _jump_to_search_match(self, direction: int) -> None:
        regex = self._compile_search_pattern(self._search_pattern)
        if regex is None:
            return
        cursor = self.textCursor()
        if cursor.hasSelection():
            # Already sitting on a match (from a previous n/N): search from its
            # far edge so repeated presses advance instead of re-matching it.
            from_pos = cursor.selectionEnd() if direction > 0 else cursor.selectionStart()
        else:
            from_pos = cursor.position() + 1 if direction > 0 else cursor.position()
        match = self._find_match(regex, from_pos, forward=direction > 0)
        if match is None:
            return
        self._enter_visual_mode()
        self._select_match(match)

    def _select_match(self, match: re.Match) -> None:
        cursor = self.textCursor()
        cursor.setPosition(match.start())
        cursor.setPosition(match.end(), QTextCursor.KeepAnchor)
        self.setTextCursor(cursor)
        self.ensureCursorVisible()

    @staticmethod
    def _compile_search_pattern(pattern: str) -> re.Pattern | None:
        """Compile `pattern`, smartcase-style: an all-lowercase pattern matches
        either case, but any uppercase letter in it makes the match case-sensitive.
        """
        if not pattern:
            return None
        flags = 0 if any(ch.isupper() for ch in pattern) else re.IGNORECASE
        try:
            return re.compile(pattern, flags)
        except re.error:
            return None

    def _find_match(self, regex: re.Pattern, from_pos: int, forward: bool) -> re.Match | None:
        """Nearest match to `from_pos`, wrapping around the document if needed."""
        matches = list(regex.finditer(self.toPlainText()))
        if not matches:
            return None
        if forward:
            for match in matches:
                if match.start() >= from_pos:
                    return match
            return matches[0]
        for match in reversed(matches):
            if match.start() < from_pos:
                return match
        return matches[-1]

    def _move(self, operation) -> None:
        cursor = self.textCursor()
        move_mode = QTextCursor.KeepAnchor if self.mode == self.VISUAL else QTextCursor.MoveAnchor
        cursor.movePosition(operation, move_mode)
        self.setTextCursor(cursor)

    def _move_to_line_start(self) -> None:
        self._set_position(self.textCursor().block().position())

    def _move_to_line_end(self) -> None:
        block = self.textCursor().block()
        self._set_position(block.position() + len(block.text()))

    def _move_down_line(self) -> None:
        cursor = self.textCursor()
        block = cursor.block()
        next_block = block.next()
        if not next_block.isValid():
            return
        column = cursor.position() - block.position()
        self._set_position(next_block.position() + min(column, len(next_block.text())))

    def _move_up_line(self) -> None:
        cursor = self.textCursor()
        block = cursor.block()
        previous_block = block.previous()
        if not previous_block.isValid():
            return
        column = cursor.position() - block.position()
        self._set_position(previous_block.position() + min(column, len(previous_block.text())))

    def _move_to_word_end(self, is_token_char) -> None:
        """Handle the `e`/`E` motions.

        Vim's `e` is documented as an *inclusive* motion (unlike most
        others, which are exclusive): in visual mode the target character
        itself is part of the selection. So in normal mode the cursor
        rests directly on the last token character, while in visual mode
        the selection is extended one further, to include it.
        """
        last_char_index = self._end_of_token_index(is_token_char)
        if last_char_index is None:
            return
        cursor = self.textCursor()
        if self.mode == self.VISUAL:
            cursor.setPosition(last_char_index + 1, QTextCursor.KeepAnchor)
        else:
            cursor.setPosition(last_char_index, QTextCursor.MoveAnchor)
        self.setTextCursor(cursor)

    def _move_to_next_word_start(self, is_token_char) -> None:
        new_position = self._next_token_start_index(is_token_char)
        if new_position is not None:
            self._set_position(new_position)

    def _move_to_previous_word_start(self, is_token_char) -> None:
        new_position = self._previous_token_start_index(is_token_char)
        if new_position is not None:
            self._set_position(new_position)

    def _set_position(self, position: int) -> None:
        cursor = self.textCursor()
        move_mode = QTextCursor.KeepAnchor if self.mode == self.VISUAL else QTextCursor.MoveAnchor
        cursor.setPosition(position, move_mode)
        self.setTextCursor(cursor)

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

    def _jump_to_first_visible_line(self) -> None:
        starts = self._visible_line_starts()
        if starts:
            self._set_position(starts[0])

    def _jump_to_last_visible_line(self) -> None:
        starts = self._visible_line_starts()
        if starts:
            self._set_position(starts[-1])

    def _jump_to_middle_visible_line(self) -> None:
        starts = self._visible_line_starts()
        if starts:
            self._set_position(starts[len(starts) // 2])

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

    def _find_char(self, char: str, direction: int) -> None:
        """Handle the `f`/`F` motions: jump to the next/previous occurrence
        of `char` anywhere in the document (case-sensitive), crossing line
        boundaries freely.
        """
        text = self.toPlainText()
        position = self.textCursor().position()

        if direction > 0:
            index = text.find(char, position + 1)
        else:
            index = text.rfind(char, 0, position)
        if index == -1:
            return
        self._set_position(index)

    def _end_of_token_index(self, is_token_char) -> int | None:
        """String index of the last character of the current/next token.

        Unlike Qt's built-in EndOfWord, this never lands on whitespace (or,
        for the plain-word predicate, punctuation either): runs of
        non-token characters are always crossed in one step rather than
        stopping partway through, whether that's a single space or a run
        of punctuation and whitespace together.
        """
        text = self.toPlainText()
        length = len(text)
        if length == 0:
            return None

        index = self.textCursor().position() + 1
        while index < length and not is_token_char(text[index]):
            index += 1
        if index >= length:
            return None  # no further token in the document

        while index + 1 < length and is_token_char(text[index + 1]):
            index += 1
        return index

    def _next_token_start_index(self, is_token_char) -> int | None:
        """String index of the start of the next token (vim's w/W)."""
        text = self.toPlainText()
        length = len(text)
        if length == 0:
            return None

        index = self.textCursor().position()
        if index < length and is_token_char(text[index]):
            while index < length and is_token_char(text[index]):
                index += 1
        while index < length and text[index].isspace():
            index += 1
        if index >= length:
            return None
        return index

    def _previous_token_start_index(self, is_token_char) -> int | None:
        """String index of the start of the previous token (vim's b/B)."""
        text = self.toPlainText()
        index = self.textCursor().position() - 1
        if index < 0:
            return None

        while index >= 0 and text[index].isspace():
            index -= 1
        if index < 0:
            return None

        while index > 0 and is_token_char(text[index - 1]):
            index -= 1
        return index

    @staticmethod
    def _is_word_char(char: str) -> bool:
        return char.isalnum() or char == "_"

    @staticmethod
    def _is_big_word_char(char: str) -> bool:
        return not char.isspace()

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
        """Fill `rect` with alternating diagonal (bottom-left to top-right)
        stripes cycling through `colors`, each roughly two characters wide,
        so a span coded with multiple codes shows every color at once
        instead of only the last one painted over the rest."""
        stripe_width = max(self.fontMetrics().averageCharWidth() * STRIPE_WIDTH_IN_CHARS, 1)
        shear = rect.height()

        painter.save()
        painter.setClipRect(rect, Qt.IntersectClip)
        painter.setPen(Qt.NoPen)
        x = rect.left() - shear
        index = 0
        while x < rect.right() + shear:
            painter.setBrush(colors[index % len(colors)])
            painter.drawPolygon(
                QPolygonF(
                    [
                        QPointF(x, rect.bottom()),
                        QPointF(x + shear, rect.top()),
                        QPointF(x + shear + stripe_width, rect.top()),
                        QPointF(x + stripe_width, rect.bottom()),
                    ]
                )
            )
            x += stripe_width
            index += 1
        painter.restore()

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
