from __future__ import annotations

import re

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPalette, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QPlainTextEdit, QTextEdit


class VimTextViewer(QPlainTextEdit):
    """A read-only text viewer navigable with vim-style keybindings.

    Normal mode moves a visible block cursor with h/j/k/l, w/b/e, 0/$, gg/G.
    Pressing v enters visual mode, where the same motions extend a text
    selection instead of just moving the cursor. Shift+W/B/E are vim's
    "WORD" variants: they treat any run of non-blank characters as a
    single unit, so punctuation around or inside a word never stops them
    (unlike lowercase w/b/e, which treat punctuation as its own word).

    G/gg jump to the bottom/top of the whole document. Shift+H/L are
    viewport-relative instead: H jumps to the start of the first line
    currently visible in the viewport, L to the start of the last one.

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
    """

    NORMAL = "normal"
    VISUAL = "visual"
    SEARCH = "search"

    modeChanged = Signal(str)
    searchTextChanged = Signal(str)

    # Keyed by key code (not text) so Shift-based case doesn't matter here;
    # shifted letters (W/B/E, G) are disambiguated via the Shift modifier.
    _MOTION_KEYS = {
        Qt.Key_J: QTextCursor.Down,
        Qt.Key_K: QTextCursor.Up,
        Qt.Key_Left: QTextCursor.Left,  # alias, doesn't conflict with code-cycling (Up/Down only)
        Qt.Key_Right: QTextCursor.Right,
    }
    _SYMBOL_MOTIONS = {
        "0": QTextCursor.StartOfLine,
        "$": QTextCursor.EndOfLine,
    }

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setCursorWidth(0)  # we render our own block cursor instead

        # Visual-mode selection uses Qt's native text-selection rendering
        # (QPalette::Highlight/HighlightedText), which defaults to a blue
        # background with white text on most platforms.
        palette = self.palette()
        palette.setColor(QPalette.Highlight, QColor(255, 255, 255))
        palette.setColor(QPalette.HighlightedText, QColor(0, 0, 0))
        self.setPalette(palette)

        self.mode = self.NORMAL
        self._pending_g = False
        self._code_highlights: list[QTextEdit.ExtraSelection] = []
        self._search_pattern = ""
        self._search_buffer = ""
        self._search_origin = 0

        self.cursorPositionChanged.connect(self._refresh_extra_selections)
        self._refresh_extra_selections()

    def set_code_highlights(self, selections: list[QTextEdit.ExtraSelection]) -> None:
        self._code_highlights = list(selections)
        self._refresh_extra_selections()

    def exit_visual_mode(self) -> None:
        if self.mode != self.VISUAL:
            return
        self.mode = self.NORMAL
        cursor = self.textCursor()
        cursor.clearSelection()
        self.setTextCursor(cursor)
        self.modeChanged.emit(self.mode)

    def keyPressEvent(self, event) -> None:
        if self.mode == self.SEARCH:
            self._handle_search_key(event)
            return

        key = event.key()
        text = event.text()
        shift = bool(event.modifiers() & Qt.ShiftModifier)

        if key == Qt.Key_Escape:
            self._pending_g = False
            self.exit_visual_mode()
            event.accept()
            return

        if key == Qt.Key_V:
            self._pending_g = False
            self._toggle_visual_mode()
            event.accept()
            return

        if key == Qt.Key_G:
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

        self._pending_g = False

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

        operation = self._MOTION_KEYS.get(key, self._SYMBOL_MOTIONS.get(text))
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

    def _refresh_extra_selections(self) -> None:
        selections = list(self._code_highlights)
        selections.append(self._cursor_highlight_selection())
        super().setExtraSelections(selections)

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
        fmt.setBackground(QColor(255, 255, 255))
        fmt.setForeground(QColor(0, 0, 0))

        selection = QTextEdit.ExtraSelection()
        selection.cursor = block_cursor
        selection.format = fmt
        return selection
