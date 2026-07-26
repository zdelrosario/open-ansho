from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QPlainTextEdit, QTextEdit


class VimTextViewer(QPlainTextEdit):
    """A read-only text viewer navigable with vim-style keybindings.

    Normal mode moves a visible block cursor with h/j/k/l, w/b/e, 0/$, gg/G.
    Pressing v enters visual mode, where the same motions extend a text
    selection instead of just moving the cursor. Shift+W/B/E are vim's
    "WORD" variants: they treat any run of non-blank characters as a
    single unit, so punctuation around or inside a word never stops them
    (unlike lowercase w/b/e, which treat punctuation as its own word).
    """

    NORMAL = "normal"
    VISUAL = "visual"

    modeChanged = Signal(str)

    # Keyed by key code (not text) so Shift-based case doesn't matter here;
    # shifted letters (W/B/E, G) are disambiguated via the Shift modifier.
    _MOTION_KEYS = {
        Qt.Key_H: QTextCursor.Left,
        Qt.Key_L: QTextCursor.Right,
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

        self.mode = self.NORMAL
        self._pending_g = False
        self._code_highlights: list[QTextEdit.ExtraSelection] = []

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
            self.mode = self.VISUAL
            self.modeChanged.emit(self.mode)

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
        if not block_cursor.atEnd():
            block_cursor.movePosition(QTextCursor.NextCharacter, QTextCursor.KeepAnchor)

        fmt = QTextCharFormat()
        fmt.setBackground(QColor(200, 200, 200))
        fmt.setForeground(QColor(0, 0, 0))

        selection = QTextEdit.ExtraSelection()
        selection.cursor = block_cursor
        selection.format = fmt
        return selection
