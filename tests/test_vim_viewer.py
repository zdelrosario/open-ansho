from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent, QTextCursor
from PySide6.QtTest import QTest

from openansho.ui.vim_viewer import VimTextViewer


def _make_viewer(qtbot, text="Hello frustrating world.\nSecond line here."):
    viewer = VimTextViewer()
    qtbot.addWidget(viewer)
    viewer.setPlainText(text)
    viewer.moveCursor(QTextCursor.Start)
    viewer.show()
    return viewer


def test_starts_in_normal_mode_with_no_selection(qtbot):
    viewer = _make_viewer(qtbot)
    assert viewer.mode == VimTextViewer.NORMAL
    assert not viewer.textCursor().hasSelection()


def test_l_moves_cursor_right_without_selecting(qtbot):
    viewer = _make_viewer(qtbot)
    viewer.setFocus()

    QTest.keyClick(viewer, Qt.Key_L)

    assert viewer.textCursor().position() == 1
    assert not viewer.textCursor().hasSelection()


def test_h_moves_cursor_left(qtbot):
    viewer = _make_viewer(qtbot)
    viewer.setFocus()
    QTest.keyClick(viewer, Qt.Key_L)
    QTest.keyClick(viewer, Qt.Key_L)
    QTest.keyClick(viewer, Qt.Key_H)

    assert viewer.textCursor().position() == 1


def test_j_moves_cursor_down_a_line(qtbot):
    viewer = _make_viewer(qtbot)
    viewer.setFocus()

    QTest.keyClick(viewer, Qt.Key_J)

    cursor = viewer.textCursor()
    assert cursor.blockNumber() == 1


def test_dollar_moves_to_end_of_line(qtbot):
    viewer = _make_viewer(qtbot)
    viewer.setFocus()

    QTest.keyClick(viewer, Qt.Key_Dollar)

    cursor = viewer.textCursor()
    assert cursor.atBlockEnd()


def test_e_moves_to_end_of_word(qtbot):
    viewer = _make_viewer(qtbot)
    viewer.setFocus()

    QTest.keyClick(viewer, Qt.Key_E)

    assert viewer.textCursor().position() == 4  # rests on "o", the last letter of "Hello"
    assert not viewer.textCursor().hasSelection()


def test_visual_mode_e_extends_selection_to_end_of_word(qtbot):
    viewer = _make_viewer(qtbot)
    viewer.setFocus()

    QTest.keyClick(viewer, Qt.Key_V)
    QTest.keyClick(viewer, Qt.Key_E)

    assert viewer.textCursor().selectedText() == "Hello"


def test_e_skips_trailing_punctuation(qtbot):
    viewer = _make_viewer(qtbot, "Hello, world.")
    viewer.setFocus()

    QTest.keyClick(viewer, Qt.Key_E)
    assert viewer.toPlainText()[viewer.textCursor().position()] == "o"  # "Hello", not ","

    QTest.keyClick(viewer, Qt.Key_E)
    assert viewer.toPlainText()[viewer.textCursor().position()] == "d"  # "world", not "."

    # No further word after the trailing period: pressing e again is a no-op.
    position_before = viewer.textCursor().position()
    QTest.keyClick(viewer, Qt.Key_E)
    assert viewer.textCursor().position() == position_before


def test_e_crosses_multiple_spaces_in_one_press(qtbot):
    viewer = _make_viewer(qtbot, "foo    bar")
    viewer.setFocus()

    QTest.keyClick(viewer, Qt.Key_E)
    assert viewer.toPlainText()[viewer.textCursor().position()] == "o"  # end of "foo"

    QTest.keyClick(viewer, Qt.Key_E)
    assert viewer.toPlainText()[viewer.textCursor().position()] == "r"  # end of "bar", not stuck in spaces


def test_capital_g_moves_to_document_end(qtbot):
    viewer = _make_viewer(qtbot)
    viewer.setFocus()

    QTest.keyClick(viewer, Qt.Key_G, Qt.ShiftModifier)

    assert viewer.textCursor().atEnd()
    assert not viewer.textCursor().hasSelection()


def test_capital_h_moves_to_first_visible_line(qtbot):
    text = "\n".join(f"Line {i}" for i in range(50))
    viewer = _make_viewer(qtbot, text)
    viewer.setFocus()

    QTest.keyClick(viewer, Qt.Key_J)
    QTest.keyClick(viewer, Qt.Key_J)
    assert viewer.textCursor().blockNumber() == 2

    QTest.keyClick(viewer, Qt.Key_H, Qt.ShiftModifier)

    assert viewer.textCursor().position() == 0
    assert not viewer.textCursor().hasSelection()


def test_capital_l_moves_to_last_visible_line(qtbot):
    text = "\n".join(f"Line {i}" for i in range(50))
    viewer = _make_viewer(qtbot, text)
    viewer.setFocus()

    starts = viewer._visible_line_starts()
    assert len(starts) >= 2  # sanity: the viewport shows multiple lines
    expected_position = starts[-1]

    QTest.keyClick(viewer, Qt.Key_L, Qt.ShiftModifier)

    assert viewer.textCursor().position() == expected_position
    assert not viewer.textCursor().hasSelection()


def test_capital_l_falls_back_to_the_only_visible_line(qtbot):
    viewer = _make_viewer(qtbot, "Just one line of text.")
    viewer.setFocus()

    QTest.keyClick(viewer, Qt.Key_L, Qt.ShiftModifier)

    assert viewer.textCursor().position() == 0


def test_gg_moves_to_document_start(qtbot):
    viewer = _make_viewer(qtbot)
    viewer.setFocus()
    QTest.keyClick(viewer, Qt.Key_G, Qt.ShiftModifier)  # go to end first
    assert viewer.textCursor().atEnd()

    QTest.keyClick(viewer, Qt.Key_G)
    QTest.keyClick(viewer, Qt.Key_G)

    assert viewer.textCursor().position() == 0


def test_zz_centers_viewport_without_moving_cursor(qtbot, monkeypatch):
    viewer = _make_viewer(qtbot)
    viewer.setFocus()
    QTest.keyClick(viewer, Qt.Key_L)
    position_before = viewer.textCursor().position()

    calls = []
    monkeypatch.setattr(viewer, "centerCursor", lambda: calls.append(True))

    QTest.keyClick(viewer, Qt.Key_Z)
    assert calls == []  # a single z does not center yet

    QTest.keyClick(viewer, Qt.Key_Z)
    assert calls == [True]
    assert viewer.textCursor().position() == position_before


def test_zt_scrolls_current_line_to_top_without_moving_cursor(qtbot, monkeypatch):
    viewer = _make_viewer(qtbot)
    viewer.setFocus()
    QTest.keyClick(viewer, Qt.Key_L)
    position_before = viewer.textCursor().position()

    calls = []
    monkeypatch.setattr(viewer, "_scroll_current_line_to_top", lambda: calls.append(True))

    QTest.keyClick(viewer, Qt.Key_Z)
    assert calls == []  # a lone z does not scroll yet

    QTest.keyClick(viewer, Qt.Key_T)
    assert calls == [True]
    assert viewer.textCursor().position() == position_before


def test_zb_scrolls_current_line_to_bottom_without_moving_cursor(qtbot, monkeypatch):
    viewer = _make_viewer(qtbot)
    viewer.setFocus()
    QTest.keyClick(viewer, Qt.Key_L)
    position_before = viewer.textCursor().position()

    calls = []
    monkeypatch.setattr(viewer, "_scroll_current_line_to_bottom", lambda: calls.append(True))

    QTest.keyClick(viewer, Qt.Key_Z)
    QTest.keyClick(viewer, Qt.Key_B)
    assert calls == [True]
    assert viewer.textCursor().position() == position_before


def test_z_then_other_key_does_not_scroll(qtbot, monkeypatch):
    viewer = _make_viewer(qtbot)
    viewer.setFocus()

    top_calls = []
    bottom_calls = []
    monkeypatch.setattr(viewer, "_scroll_current_line_to_top", lambda: top_calls.append(True))
    monkeypatch.setattr(viewer, "_scroll_current_line_to_bottom", lambda: bottom_calls.append(True))

    QTest.keyClick(viewer, Qt.Key_Z)
    QTest.keyClick(viewer, Qt.Key_L)

    assert top_calls == []
    assert bottom_calls == []
    assert viewer.textCursor().position() == 1


def test_ctrl_e_scrolls_viewport_down_one_line(qtbot, monkeypatch):
    viewer = _make_viewer(qtbot)
    viewer.setFocus()
    position_before = viewer.textCursor().position()

    calls = []
    monkeypatch.setattr(viewer, "_scroll_viewport_lines", lambda delta: calls.append(delta))

    QTest.keyClick(viewer, Qt.Key_E, Qt.ControlModifier)

    assert calls == [1]
    assert viewer.textCursor().position() == position_before


def test_ctrl_y_scrolls_viewport_up_one_line(qtbot, monkeypatch):
    viewer = _make_viewer(qtbot)
    viewer.setFocus()
    position_before = viewer.textCursor().position()

    calls = []
    monkeypatch.setattr(viewer, "_scroll_viewport_lines", lambda delta: calls.append(delta))

    QTest.keyClick(viewer, Qt.Key_Y, Qt.ControlModifier)

    assert calls == [-1]
    assert viewer.textCursor().position() == position_before


def test_cursor_highlight_stays_visible_at_document_end(qtbot):
    viewer = _make_viewer(qtbot, "Hi")
    viewer.setFocus()

    QTest.keyClick(viewer, Qt.Key_G, Qt.ShiftModifier)
    assert viewer.textCursor().atEnd()

    selections = viewer.extraSelections()
    assert len(selections) == 1
    assert selections[0].cursor.hasSelection()


def test_v_enters_visual_mode(qtbot):
    viewer = _make_viewer(qtbot)
    viewer.setFocus()

    QTest.keyClick(viewer, Qt.Key_V)

    assert viewer.mode == VimTextViewer.VISUAL


def test_visual_mode_motions_extend_selection(qtbot):
    viewer = _make_viewer(qtbot)
    viewer.setFocus()

    QTest.keyClick(viewer, Qt.Key_V)
    for _ in range(5):
        QTest.keyClick(viewer, Qt.Key_L)

    cursor = viewer.textCursor()
    assert cursor.hasSelection()
    assert cursor.selectedText() == "Hello"


def test_shift_v_enters_visual_mode_and_selects_current_line(qtbot):
    viewer = _make_viewer(qtbot)
    viewer.setFocus()
    QTest.keyClick(viewer, Qt.Key_L)
    QTest.keyClick(viewer, Qt.Key_L)

    QTest.keyClick(viewer, Qt.Key_V, Qt.ShiftModifier)

    assert viewer.mode == VimTextViewer.VISUAL
    cursor = viewer.textCursor()
    assert cursor.hasSelection()
    assert cursor.selectedText() == "Hello frustrating world."


def test_shift_v_selects_current_line_on_second_line(qtbot):
    viewer = _make_viewer(qtbot)
    viewer.setFocus()
    QTest.keyClick(viewer, Qt.Key_G, Qt.ShiftModifier)

    QTest.keyClick(viewer, Qt.Key_V, Qt.ShiftModifier)

    cursor = viewer.textCursor()
    assert cursor.hasSelection()
    assert cursor.selectedText() == "Second line here."


def test_v_again_exits_visual_mode_and_clears_selection(qtbot):
    viewer = _make_viewer(qtbot)
    viewer.setFocus()

    QTest.keyClick(viewer, Qt.Key_V)
    QTest.keyClick(viewer, Qt.Key_L)
    assert viewer.textCursor().hasSelection()

    QTest.keyClick(viewer, Qt.Key_V)

    assert viewer.mode == VimTextViewer.NORMAL
    assert not viewer.textCursor().hasSelection()


def test_escape_exits_visual_mode_and_clears_selection(qtbot):
    viewer = _make_viewer(qtbot)
    viewer.setFocus()

    QTest.keyClick(viewer, Qt.Key_V)
    QTest.keyClick(viewer, Qt.Key_L)
    assert viewer.textCursor().hasSelection()

    QTest.keyClick(viewer, Qt.Key_Escape)

    assert viewer.mode == VimTextViewer.NORMAL
    assert not viewer.textCursor().hasSelection()


def test_visual_mode_preserves_an_existing_mouse_style_selection(qtbot):
    viewer = _make_viewer(qtbot)
    cursor = viewer.textCursor()
    cursor.setPosition(6)
    cursor.setPosition(17, QTextCursor.KeepAnchor)
    viewer.setTextCursor(cursor)
    viewer.setFocus()

    QTest.keyClick(viewer, Qt.Key_V)

    assert viewer.textCursor().selectedText() == "frustrating"
    assert viewer.mode == VimTextViewer.VISUAL


def test_code_highlights_and_cursor_block_coexist(qtbot):
    from PySide6.QtGui import QColor

    from openansho.ui.vim_viewer import CodeHighlight

    viewer = _make_viewer(qtbot)
    viewer.set_code_highlights(
        [CodeHighlight(start=0, end=5, color=QColor("#ffff00"), band_index=0, band_count=1)]
    )

    # Code highlights are painted separately, not via QPlainTextEdit's
    # extraSelections mechanism, so only the vim block cursor lives there.
    assert len(viewer.extraSelections()) == 1
    assert viewer._code_highlights[0].start == 0
    assert viewer._code_highlights[0].end == 5


def test_shift_w_treats_attached_punctuation_as_part_of_the_word(qtbot):
    viewer = _make_viewer(qtbot, "Hello, world. Next")
    viewer.setFocus()

    QTest.keyClick(viewer, Qt.Key_W, Qt.ShiftModifier)
    assert viewer.textCursor().position() == 7  # start of "world.", "Hello," skipped whole

    QTest.keyClick(viewer, Qt.Key_W, Qt.ShiftModifier)
    assert viewer.textCursor().position() == 14  # start of "Next", "world." skipped whole


def test_shift_b_treats_attached_punctuation_as_part_of_the_word(qtbot):
    viewer = _make_viewer(qtbot, "Hello, world. Next")
    cursor = viewer.textCursor()
    cursor.setPosition(14)
    viewer.setTextCursor(cursor)
    viewer.setFocus()

    QTest.keyClick(viewer, Qt.Key_B, Qt.ShiftModifier)
    assert viewer.textCursor().position() == 7  # back to start of "world."

    QTest.keyClick(viewer, Qt.Key_B, Qt.ShiftModifier)
    assert viewer.textCursor().position() == 0  # back to start of "Hello,"


def test_shift_e_includes_trailing_punctuation_in_the_word(qtbot):
    viewer = _make_viewer(qtbot, "Hello, world. Next")
    viewer.setFocus()

    QTest.keyClick(viewer, Qt.Key_E, Qt.ShiftModifier)
    assert viewer.toPlainText()[viewer.textCursor().position()] == ","

    QTest.keyClick(viewer, Qt.Key_E, Qt.ShiftModifier)
    assert viewer.toPlainText()[viewer.textCursor().position()] == "."


def test_visual_mode_shift_e_selects_through_punctuation(qtbot):
    viewer = _make_viewer(qtbot, "Hello, world. Next")
    viewer.setFocus()

    QTest.keyClick(viewer, Qt.Key_V)
    QTest.keyClick(viewer, Qt.Key_E, Qt.ShiftModifier)

    assert viewer.textCursor().selectedText() == "Hello,"


def test_lowercase_e_still_stops_before_punctuation_unlike_shift_e(qtbot):
    viewer = _make_viewer(qtbot, "Hello, world. Next")
    viewer.setFocus()

    QTest.keyClick(viewer, Qt.Key_E)

    assert viewer.toPlainText()[viewer.textCursor().position()] == "o"  # end of "Hello", no comma


def test_slash_enters_search_mode_and_jumps_progressively_to_first_match(qtbot):
    viewer = _make_viewer(qtbot, "Hello frustrating world.")
    viewer.setFocus()

    QTest.keyClick(viewer, Qt.Key_Slash)
    assert viewer.mode == VimTextViewer.SEARCH

    QTest.keyClicks(viewer, "wor")

    assert viewer.textCursor().selectedText() == "wor"
    assert viewer.textCursor().selectionStart() == 18


def test_search_pattern_is_a_regular_expression(qtbot):
    viewer = _make_viewer(qtbot, "Hello frustrating world.")
    viewer.setFocus()

    QTest.keyClick(viewer, Qt.Key_Slash)
    QTest.keyClicks(viewer, "w.rld")

    assert viewer.textCursor().selectedText() == "world"


def test_enter_commits_search_and_leaves_cursor_on_match_without_selection(qtbot):
    viewer = _make_viewer(qtbot, "Hello frustrating world.")
    viewer.setFocus()

    QTest.keyClick(viewer, Qt.Key_Slash)
    QTest.keyClicks(viewer, "wor")
    QTest.keyClick(viewer, Qt.Key_Return)

    assert viewer.mode == VimTextViewer.NORMAL
    assert not viewer.textCursor().hasSelection()
    assert viewer.textCursor().position() == 18


def test_escape_during_search_cancels_and_restores_cursor_position(qtbot):
    viewer = _make_viewer(qtbot, "Hello frustrating world.")
    viewer.setFocus()
    cursor = viewer.textCursor()
    cursor.setPosition(6)
    viewer.setTextCursor(cursor)

    QTest.keyClick(viewer, Qt.Key_Slash)
    QTest.keyClicks(viewer, "wor")
    assert viewer.textCursor().hasSelection()

    QTest.keyClick(viewer, Qt.Key_Escape)

    assert viewer.mode == VimTextViewer.NORMAL
    assert not viewer.textCursor().hasSelection()
    assert viewer.textCursor().position() == 6


def test_n_and_shift_n_cycle_forward_and_backward_through_matches(qtbot):
    viewer = _make_viewer(qtbot, "cat hat cat mat cat")
    viewer.setFocus()

    QTest.keyClick(viewer, Qt.Key_Slash)
    QTest.keyClicks(viewer, "cat")
    QTest.keyClick(viewer, Qt.Key_Return)
    assert viewer.mode == VimTextViewer.NORMAL
    assert not viewer.textCursor().hasSelection()
    assert viewer.textCursor().position() == 0

    QTest.keyClick(viewer, Qt.Key_N)
    assert viewer.mode == VimTextViewer.VISUAL
    assert (viewer.textCursor().selectionStart(), viewer.textCursor().selectionEnd()) == (8, 11)

    QTest.keyClick(viewer, Qt.Key_N)
    assert (viewer.textCursor().selectionStart(), viewer.textCursor().selectionEnd()) == (16, 19)

    QTest.keyClick(viewer, Qt.Key_N)  # wraps back to the first match
    assert (viewer.textCursor().selectionStart(), viewer.textCursor().selectionEnd()) == (0, 3)

    QTest.keyClick(viewer, Qt.Key_N, Qt.ShiftModifier)  # wraps backward to the last match
    assert (viewer.textCursor().selectionStart(), viewer.textCursor().selectionEnd()) == (16, 19)

    QTest.keyClick(viewer, Qt.Key_N, Qt.ShiftModifier)
    assert (viewer.textCursor().selectionStart(), viewer.textCursor().selectionEnd()) == (8, 11)
    assert viewer.mode == VimTextViewer.VISUAL


def test_n_without_a_committed_search_does_nothing(qtbot):
    viewer = _make_viewer(qtbot, "cat hat cat")
    viewer.setFocus()

    QTest.keyClick(viewer, Qt.Key_N)

    assert viewer.textCursor().position() == 0
    assert viewer.mode == VimTextViewer.NORMAL


def test_lowercase_search_pattern_matches_either_case(qtbot):
    viewer = _make_viewer(qtbot, "Hello World")
    viewer.setFocus()

    QTest.keyClick(viewer, Qt.Key_Slash)
    QTest.keyClicks(viewer, "world")

    assert viewer.textCursor().selectedText() == "World"


def test_uppercase_letter_in_pattern_matches_only_uppercase(qtbot):
    viewer = _make_viewer(qtbot, "hello World")
    viewer.setFocus()

    QTest.keyClick(viewer, Qt.Key_Slash)
    QTest.keyClicks(viewer, "World")

    assert viewer.textCursor().selectedText() == "World"


def test_uppercase_letter_in_pattern_does_not_match_lowercase(qtbot):
    viewer = _make_viewer(qtbot, "hello world")
    viewer.setFocus()

    QTest.keyClick(viewer, Qt.Key_Slash)
    QTest.keyClicks(viewer, "World")

    assert not viewer.textCursor().hasSelection()
    assert viewer.textCursor().position() == 0


def test_f_moves_cursor_forward_to_next_occurrence_of_char(qtbot):
    viewer = _make_viewer(qtbot, "Hello frustrating world.")
    viewer.setFocus()

    QTest.keyClick(viewer, Qt.Key_F)
    QTest.keyClicks(viewer, "w")

    assert viewer.textCursor().position() == 18
    assert not viewer.textCursor().hasSelection()


def test_capital_f_moves_cursor_backward_to_previous_occurrence(qtbot):
    viewer = _make_viewer(qtbot, "Hello frustrating world.")
    viewer.setFocus()
    cursor = viewer.textCursor()
    cursor.setPosition(20)
    viewer.setTextCursor(cursor)

    QTest.keyClick(viewer, Qt.Key_F, Qt.ShiftModifier)
    QTest.keyClicks(viewer, "r")

    assert viewer.textCursor().position() == 11


def test_f_crosses_line_boundary(qtbot):
    viewer = _make_viewer(qtbot, "Hello frustrating world.\nSecond line here.")
    viewer.setFocus()

    QTest.keyClick(viewer, Qt.Key_F)
    QTest.keyClicks(viewer, "S")

    assert viewer.textCursor().position() == 25
    assert not viewer.textCursor().hasSelection()


def test_f_is_case_sensitive(qtbot):
    viewer = _make_viewer(qtbot, "Hello frustrating world.")
    viewer.setFocus()

    QTest.keyClick(viewer, Qt.Key_F)
    QTest.keyClicks(viewer, "W")

    assert viewer.textCursor().position() == 0
    assert not viewer.textCursor().hasSelection()


def test_f_capital_letter_search_survives_a_leading_bare_shift_keypress(qtbot):
    # Qt delivers holding Shift as its own keypress (Key_Shift, no text)
    # before the shifted letter arrives. That bare press must not consume
    # the pending f/F state, or the real target character falls through to
    # ordinary key handling instead of being searched for.
    viewer = _make_viewer(qtbot, "Hello frustrating World.")
    viewer.setFocus()

    QTest.keyClick(viewer, Qt.Key_F)
    viewer.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Shift, Qt.ShiftModifier, ""))
    viewer.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_W, Qt.ShiftModifier, "W"))

    assert viewer.textCursor().position() == 18
    assert not viewer.textCursor().hasSelection()


def test_f_with_no_match_does_not_move_cursor(qtbot):
    viewer = _make_viewer(qtbot, "Hello frustrating world.")
    viewer.setFocus()

    QTest.keyClick(viewer, Qt.Key_F)
    QTest.keyClicks(viewer, "z")

    assert viewer.textCursor().position() == 0
    assert not viewer.textCursor().hasSelection()


def test_i_enters_insert_mode(qtbot):
    viewer = _make_viewer(qtbot)
    viewer.setFocus()

    QTest.keyClick(viewer, Qt.Key_I)

    assert viewer.mode == VimTextViewer.INSERT
    assert not viewer.isReadOnly()


def test_escape_in_insert_mode_returns_to_normal_mode(qtbot):
    viewer = _make_viewer(qtbot)
    viewer.setFocus()
    QTest.keyClick(viewer, Qt.Key_I)

    QTest.keyClick(viewer, Qt.Key_Escape)

    assert viewer.mode == VimTextViewer.NORMAL
    assert viewer.isReadOnly()


def test_i_in_visual_mode_does_not_enter_insert_mode(qtbot):
    viewer = _make_viewer(qtbot)
    viewer.setFocus()
    QTest.keyClick(viewer, Qt.Key_V)

    QTest.keyClick(viewer, Qt.Key_I)

    assert viewer.mode == VimTextViewer.VISUAL


def test_insert_mode_hides_the_block_cursor_highlight(qtbot):
    viewer = _make_viewer(qtbot)
    viewer.setFocus()

    QTest.keyClick(viewer, Qt.Key_I)

    assert viewer.extraSelections() == []


def test_typing_in_insert_mode_edits_the_document_and_emits_content_edited(qtbot):
    viewer = _make_viewer(qtbot, "Hello world.")
    viewer.setFocus()
    QTest.keyClick(viewer, Qt.Key_I)

    edits = []
    viewer.contentEdited.connect(lambda pos, removed, added: edits.append((pos, removed, added)))

    QTest.keyClicks(viewer, "X")

    assert viewer.toPlainText() == "XHello world."
    assert edits == [(0, 0, 1)]


def test_backspace_in_insert_mode_emits_content_edited_with_removal(qtbot):
    viewer = _make_viewer(qtbot, "Hello world.")
    viewer.setFocus()
    cursor = viewer.textCursor()
    cursor.setPosition(5)
    viewer.setTextCursor(cursor)
    QTest.keyClick(viewer, Qt.Key_I)

    edits = []
    viewer.contentEdited.connect(lambda pos, removed, added: edits.append((pos, removed, added)))

    QTest.keyClick(viewer, Qt.Key_Backspace)

    assert viewer.toPlainText() == "Hell world."
    assert edits == [(4, 1, 0)]


def test_set_plain_text_does_not_emit_content_edited(qtbot):
    viewer = _make_viewer(qtbot, "Hello world.")

    edits = []
    viewer.contentEdited.connect(lambda pos, removed, added: edits.append((pos, removed, added)))

    viewer.setPlainText("Different text.")

    assert edits == []


def test_clear_does_not_emit_content_edited(qtbot):
    viewer = _make_viewer(qtbot, "Hello world.")

    edits = []
    viewer.contentEdited.connect(lambda pos, removed, added: edits.append((pos, removed, added)))

    viewer.clear()

    assert edits == []


def test_visual_mode_f_extends_selection(qtbot):
    viewer = _make_viewer(qtbot, "Hello frustrating world.")
    viewer.setFocus()

    QTest.keyClick(viewer, Qt.Key_V)
    QTest.keyClick(viewer, Qt.Key_F)
    QTest.keyClicks(viewer, "w")

    assert viewer.mode == VimTextViewer.VISUAL
    assert viewer.textCursor().position() == 18
    assert viewer.textCursor().selectionStart() == 0
