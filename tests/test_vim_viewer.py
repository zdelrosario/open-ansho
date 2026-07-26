from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtTest import QTest

from opencoder.ui.vim_viewer import VimTextViewer


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


def test_gg_moves_to_document_start(qtbot):
    viewer = _make_viewer(qtbot)
    viewer.setFocus()
    QTest.keyClick(viewer, Qt.Key_G, Qt.ShiftModifier)  # go to end first
    assert viewer.textCursor().atEnd()

    QTest.keyClick(viewer, Qt.Key_G)
    QTest.keyClick(viewer, Qt.Key_G)

    assert viewer.textCursor().position() == 0


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
    from PySide6.QtGui import QTextCharFormat, QTextCursor
    from PySide6.QtWidgets import QTextEdit

    viewer = _make_viewer(qtbot)
    code_cursor = QTextCursor(viewer.document())
    code_cursor.setPosition(0)
    code_cursor.setPosition(5, QTextCursor.KeepAnchor)
    selection = QTextEdit.ExtraSelection()
    selection.cursor = code_cursor
    selection.format = QTextCharFormat()

    viewer.set_code_highlights([selection])

    assert len(viewer.extraSelections()) == 2  # code highlight + cursor block


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
