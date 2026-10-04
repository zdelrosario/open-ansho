"""The vim keybindings, shared by the two panes that have a text cursor.

`VimTextViewer` (plain text) and `PdfViewer` (a PDF's pages) are different
widgets drawing different things, but a cursor behaves identically in both —
so the motions, the modes and the search live here, once, and each pane
supplies only the parts that depend on what it is showing.

A host must be a QWidget that provides:

- `textCursor()` / `setTextCursor(cursor)` / `toPlainText()` / `document()`,
  with QPlainTextEdit's meaning. A pane that isn't a text widget can back
  these with a QTextDocument of its own, as `PdfViewer` does.
- `ensureCursorVisible()` and `centerCursor()`.
- `_visible_line_starts()`, `_scroll_current_line_to_top()`,
  `_scroll_current_line_to_bottom()` and `_scroll_viewport_lines(delta)` —
  the motions whose meaning depends on how the pane lays its content out.
- `modeChanged` and `searchTextChanged` signals. They are declared on each
  host rather than here because PySide only registers a Signal declared on a
  QObject subclass.
- `_on_insert_mode_changed(entering)`, called when the mode changes, for
  whatever the pane has to switch over (the text pane swaps its block cursor
  for a real one). Panes that set `supports_insert_mode = False`, as
  `PdfViewer` does, never see it: a PDF's text is a rendering of the page, so
  editing it would make the two disagree.

`_init_vim_state()` must be called from the host's `__init__`.
"""

from __future__ import annotations

import re

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor


class VimTextNavigation:
    """Vim-style modes, motions and search for a widget with a text cursor."""

    NORMAL = "normal"
    VISUAL = "visual"
    SEARCH = "search"
    INSERT = "insert"

    # Hosts that render something other than the text itself turn this off:
    # see the module docstring.
    supports_insert_mode = True

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

    def _init_vim_state(self) -> None:
        self.mode = self.NORMAL
        self._pending_g = False
        self._pending_z = False
        self._pending_find: int | None = None
        self._search_pattern = ""
        self._search_buffer = ""
        self._search_origin = 0

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

    def select_range(self, start: int, end: int) -> None:
        """Select [start, end) and enter visual mode.

        Leaves the pane exactly as if the user had made the selection with
        `v`, so the ordinary coding shortcuts (Enter, the code filter, the
        Apply button) act on it.
        """
        self._enter_visual_mode()
        cursor = self.textCursor()
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.KeepAnchor)
        self.setTextCursor(cursor)
        self.ensureCursorVisible()

    def enter_insert_mode(self) -> None:
        if self.mode == self.INSERT or not self.supports_insert_mode:
            return
        if self.mode == self.SEARCH:
            self._cancel_search()
        self.mode = self.INSERT
        self._on_insert_mode_changed(True)
        self.modeChanged.emit(self.mode)

    def exit_insert_mode(self) -> None:
        if self.mode != self.INSERT:
            return
        self.mode = self.NORMAL
        self._on_insert_mode_changed(False)
        self.modeChanged.emit(self.mode)

    def _on_insert_mode_changed(self, entering: bool) -> None:
        """Hook: whatever the pane has to switch when insert mode toggles."""

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
            if shift:
                self._select_current_line()
            else:
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

    def _select_current_line(self) -> None:
        self._enter_visual_mode()
        block = self.textCursor().block()
        cursor = self.textCursor()
        cursor.setPosition(block.position())
        cursor.setPosition(block.position() + len(block.text()), QTextCursor.KeepAnchor)
        self.setTextCursor(cursor)

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
