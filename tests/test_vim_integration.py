from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtTest import QTest

from openansho import db
from openansho.ui.main_window import MainWindow
from openansho.ui.vim_viewer import VimTextViewer


def _open_project_with_document(window, tmp_path, content="Hello frustrating world."):
    window.create_project(tmp_path / "project.sqlite")
    doc_path = tmp_path / "doc.txt"
    doc_path.write_text(content, encoding="utf-8")
    window.import_document(doc_path)
    window.document_list.setCurrentRow(0)
    return doc_path


def test_mode_label_shows_visual_when_entering_visual_mode(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    _open_project_with_document(window, tmp_path)

    assert window.vim_mode_label.text() == ""

    window.viewer.setFocus()
    qtbot.waitUntil(lambda: window.viewer.hasFocus())
    QTest.keyClick(window.viewer, Qt.Key_V)

    assert window.vim_mode_label.text() == "-- VISUAL --"

    QTest.keyClick(window.viewer, Qt.Key_V)
    assert window.vim_mode_label.text() == ""


def test_vim_selection_drives_the_always_selected_code_highlight(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    _open_project_with_document(window, tmp_path, "Hello frustrating world.")
    window.add_code("Frustration")

    cursor = window.viewer.textCursor()
    cursor.setPosition(0)
    window.viewer.setTextCursor(cursor)
    window.viewer.setFocus()
    qtbot.waitUntil(lambda: window.viewer.hasFocus())

    QTest.keyClick(window.viewer, Qt.Key_V)
    for _ in range(5):
        QTest.keyClick(window.viewer, Qt.Key_L)

    assert window.viewer.textCursor().selectedText() == "Hello"
    assert window.code_tree.currentItem() is not None
    assert window.code_tree.currentItem().text(0) == "Frustration"


def test_enter_on_viewer_applies_highlighted_code_to_vim_selection(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    _open_project_with_document(window, tmp_path, "Hello frustrating world.")
    code = window.add_code("Frustration")

    cursor = window.viewer.textCursor()
    cursor.setPosition(6)
    window.viewer.setTextCursor(cursor)
    window.viewer.setFocus()
    qtbot.waitUntil(lambda: window.viewer.hasFocus())

    QTest.keyClick(window.viewer, Qt.Key_V)
    for _ in range(10):  # select "frustrating"
        QTest.keyClick(window.viewer, Qt.Key_L)

    QTest.keyClick(window.viewer, Qt.Key_Return)

    segments = db.list_segments_for_document(window.conn, window._current_document_id)
    assert len(segments) == 1
    assert segments[0].code_id == code.id
    assert segments[0].start_offset == 6

    # Applying should exit visual mode and clear the selection.
    assert window.viewer.mode == VimTextViewer.NORMAL
    assert not window.viewer.textCursor().hasSelection()
    assert window.vim_mode_label.text() == ""


def test_enter_on_viewer_without_selection_does_nothing(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    _open_project_with_document(window, tmp_path, "Hello frustrating world.")
    window.add_code("Frustration")

    window.viewer.setFocus()
    qtbot.waitUntil(lambda: window.viewer.hasFocus())
    QTest.keyClick(window.viewer, Qt.Key_Return)

    segments = db.list_segments_for_document(window.conn, window._current_document_id)
    assert segments == []


def test_switching_documents_exits_visual_mode(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    window.create_project(tmp_path / "project.sqlite")
    (tmp_path / "a.txt").write_text("Content A here.", encoding="utf-8")
    (tmp_path / "b.txt").write_text("Content B here.", encoding="utf-8")
    window.import_document(tmp_path / "a.txt")
    window.import_document(tmp_path / "b.txt")

    window.document_list.setCurrentRow(0)
    window.viewer.setFocus()
    qtbot.waitUntil(lambda: window.viewer.hasFocus())
    QTest.keyClick(window.viewer, Qt.Key_V)
    assert window.viewer.mode == VimTextViewer.VISUAL

    window.document_list.setCurrentRow(1)

    assert window.viewer.mode == VimTextViewer.NORMAL


def test_code_highlights_survive_alongside_vim_cursor_after_apply(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    _open_project_with_document(window, tmp_path, "Hello frustrating world.")
    code = window.add_code("Frustration")
    window.apply_segment(code.id, 6, 17)

    # code highlight + vim cursor block should coexist; the code highlight is
    # painted separately, so only the cursor block lives in extraSelections()
    assert len(window.viewer.extraSelections()) == 1
    assert len(window.viewer._code_highlights) == 1


def _place_cursor(window, position):
    cursor = window.viewer.textCursor()
    cursor.setPosition(position)
    window.viewer.setTextCursor(cursor)


def test_x_deletes_segment_intersecting_cursor(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    _open_project_with_document(window, tmp_path, "Hello frustrating world.")
    code = window.add_code("Frustration")
    window.apply_segment(code.id, 6, 17)  # "frustrating"

    _place_cursor(window, 10)  # inside the coded span
    window.viewer.setFocus()
    qtbot.waitUntil(lambda: window.viewer.hasFocus())

    QTest.keyClick(window.viewer, Qt.Key_X)

    assert db.list_segments_for_document(window.conn, window._current_document_id) == []
    assert len(window.viewer.extraSelections()) == 1  # just the cursor block now


def test_x_deletes_all_overlapping_segments(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    _open_project_with_document(window, tmp_path, "Hello frustrating world.")
    code_a = window.add_code("Frustration")
    code_b = window.add_code("Emotion")
    window.apply_segment(code_a.id, 6, 17)
    window.apply_segment(code_b.id, 0, 17)  # overlaps the same cursor position too

    _place_cursor(window, 10)
    window.viewer.setFocus()
    qtbot.waitUntil(lambda: window.viewer.hasFocus())

    QTest.keyClick(window.viewer, Qt.Key_X)

    assert db.list_segments_for_document(window.conn, window._current_document_id) == []


def test_x_does_nothing_outside_any_segment(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    _open_project_with_document(window, tmp_path, "Hello frustrating world.")
    code = window.add_code("Frustration")
    window.apply_segment(code.id, 6, 17)

    _place_cursor(window, 0)  # on "Hello", outside the coded span
    window.viewer.setFocus()
    qtbot.waitUntil(lambda: window.viewer.hasFocus())

    QTest.keyClick(window.viewer, Qt.Key_X)

    segments = db.list_segments_for_document(window.conn, window._current_document_id)
    assert len(segments) == 1


def test_x_in_visual_mode_without_selection_does_nothing(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    _open_project_with_document(window, tmp_path, "Hello frustrating world.")
    code = window.add_code("Frustration")
    window.apply_segment(code.id, 6, 17)

    _place_cursor(window, 10)
    window.viewer.setFocus()
    qtbot.waitUntil(lambda: window.viewer.hasFocus())
    QTest.keyClick(window.viewer, Qt.Key_V)
    assert window.viewer.mode == VimTextViewer.VISUAL

    QTest.keyClick(window.viewer, Qt.Key_X)

    segments = db.list_segments_for_document(window.conn, window._current_document_id)
    assert len(segments) == 1


def test_x_in_visual_mode_deletes_segments_intersecting_selection(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    _open_project_with_document(window, tmp_path, "Hello frustrating world.")
    code_a = window.add_code("Frustration")
    code_b = window.add_code("Greeting")
    window.apply_segment(code_a.id, 6, 17)  # "frustrating"
    window.apply_segment(code_b.id, 0, 5)  # "Hello", outside the selection below

    _place_cursor(window, 8)  # inside "frustrating"
    window.viewer.setFocus()
    qtbot.waitUntil(lambda: window.viewer.hasFocus())

    QTest.keyClick(window.viewer, Qt.Key_V)
    for _ in range(3):
        QTest.keyClick(window.viewer, Qt.Key_L)

    segments = db.list_segments_for_document(window.conn, window._current_document_id)
    assert len(segments) == 2  # sanity check: nothing deleted yet

    QTest.keyClick(window.viewer, Qt.Key_X)

    segments = db.list_segments_for_document(window.conn, window._current_document_id)
    assert len(segments) == 1
    assert segments[0].code_id == code_b.id

    # x also exits visual mode, like Enter does.
    assert window.viewer.mode == VimTextViewer.NORMAL
    assert not window.viewer.textCursor().hasSelection()


def test_c_jumps_to_next_segment_and_wraps(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    _open_project_with_document(window, tmp_path, "Hello frustrating world.")
    code_a = window.add_code("Greeting")
    code_b = window.add_code("Frustration")
    window.apply_segment(code_a.id, 0, 5)  # "Hello"
    window.apply_segment(code_b.id, 6, 17)  # "frustrating"

    _place_cursor(window, 0)
    window.viewer.setFocus()
    qtbot.waitUntil(lambda: window.viewer.hasFocus())

    QTest.keyClick(window.viewer, Qt.Key_C)
    cursor = window.viewer.textCursor()
    assert (cursor.selectionStart(), cursor.selectionEnd()) == (6, 17)
    assert cursor.position() == 6  # cursor rests at the start of the segment

    QTest.keyClick(window.viewer, Qt.Key_C)  # wraps back to the first segment
    cursor = window.viewer.textCursor()
    assert (cursor.selectionStart(), cursor.selectionEnd()) == (0, 5)
    assert cursor.position() == 0


def test_shift_c_jumps_to_previous_segment_and_wraps(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    _open_project_with_document(window, tmp_path, "Hello frustrating world.")
    code_a = window.add_code("Greeting")
    code_b = window.add_code("Frustration")
    window.apply_segment(code_a.id, 0, 5)  # "Hello"
    window.apply_segment(code_b.id, 6, 17)  # "frustrating"

    _place_cursor(window, 20)
    window.viewer.setFocus()
    qtbot.waitUntil(lambda: window.viewer.hasFocus())

    QTest.keyClick(window.viewer, Qt.Key_C, Qt.ShiftModifier)
    cursor = window.viewer.textCursor()
    assert (cursor.selectionStart(), cursor.selectionEnd()) == (6, 17)
    assert cursor.position() == 6  # cursor rests at the start of the segment

    QTest.keyClick(window.viewer, Qt.Key_C, Qt.ShiftModifier)
    cursor = window.viewer.textCursor()
    assert (cursor.selectionStart(), cursor.selectionEnd()) == (0, 5)
    assert cursor.position() == 0

    QTest.keyClick(window.viewer, Qt.Key_C, Qt.ShiftModifier)  # wraps to the last segment
    cursor = window.viewer.textCursor()
    assert (cursor.selectionStart(), cursor.selectionEnd()) == (6, 17)
    assert cursor.position() == 6


def _check_user_filter(combo, data_value):
    for i in range(combo.model().rowCount()):
        item = combo.model().item(i)
        if item.data() == data_value:
            item.setCheckState(Qt.Checked)
            return
    raise AssertionError(f"no combo item with data {data_value!r}")


def test_c_only_cycles_through_selected_users_segments(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    _open_project_with_document(window, tmp_path, "Hello frustrating world.")
    greeting = window.add_code("Greeting")
    frustration = window.add_code("Frustration")

    window.username = "alice"
    window.apply_segment(greeting.id, 0, 5)  # "Hello"
    # bob's segment already exists in the shared project file, but bob isn't
    # among the selected users by default (only the active user, alice, is).
    db.create_segment(
        window.conn, window._current_document_id, frustration.id, 6, 17, created_by="bob"
    )
    window._refresh_user_filter()

    _place_cursor(window, 0)
    window.viewer.setFocus()
    qtbot.waitUntil(lambda: window.viewer.hasFocus())

    QTest.keyClick(window.viewer, Qt.Key_C)
    cursor = window.viewer.textCursor()
    # Wraps back to alice's own (only) segment instead of jumping to bob's.
    assert (cursor.selectionStart(), cursor.selectionEnd()) == (0, 5)

    _check_user_filter(window.user_filter_combo, "bob")
    _place_cursor(window, 0)

    QTest.keyClick(window.viewer, Qt.Key_C)
    cursor = window.viewer.textCursor()
    # Now that bob is selected too, cycling reaches his segment.
    assert (cursor.selectionStart(), cursor.selectionEnd()) == (6, 17)


def test_c_and_shift_c_do_nothing_without_segments(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    _open_project_with_document(window, tmp_path, "Hello frustrating world.")

    _place_cursor(window, 0)
    window.viewer.setFocus()
    qtbot.waitUntil(lambda: window.viewer.hasFocus())

    QTest.keyClick(window.viewer, Qt.Key_C)
    QTest.keyClick(window.viewer, Qt.Key_C, Qt.ShiftModifier)

    assert window.viewer.textCursor().position() == 0
    assert not window.viewer.textCursor().hasSelection()


def test_x_excludes_segment_ending_exactly_at_cursor(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    _open_project_with_document(window, tmp_path, "Hello frustrating world.")
    code = window.add_code("Frustration")
    window.apply_segment(code.id, 6, 17)  # "frustrating", end_offset=17

    _place_cursor(window, 17)  # right after the coded span, not inside it
    window.viewer.setFocus()
    qtbot.waitUntil(lambda: window.viewer.hasFocus())

    QTest.keyClick(window.viewer, Qt.Key_X)

    segments = db.list_segments_for_document(window.conn, window._current_document_id)
    assert len(segments) == 1


def test_search_mode_shows_indicator_and_enter_never_applies_a_code(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    _open_project_with_document(window, tmp_path, "Hello frustrating world.")
    window.add_code("Frustration")

    _place_cursor(window, 0)
    window.viewer.setFocus()
    qtbot.waitUntil(lambda: window.viewer.hasFocus())

    QTest.keyClick(window.viewer, Qt.Key_Slash)
    assert window.vim_mode_label.text() == "-- SEARCH --"

    QTest.keyClicks(window.viewer, "wor")
    assert window.viewer.textCursor().hasSelection()
    assert window.code_tree.currentItem() is not None  # search preview selects text like visual mode does

    QTest.keyClick(window.viewer, Qt.Key_Return)

    # Enter must save the search, never apply the highlighted code to the match.
    assert db.list_segments_for_document(window.conn, window._current_document_id) == []
    assert window.vim_mode_label.text() == ""
    assert window.search_label.text() == "/wor"


def test_committed_search_string_stays_visible_after_leaving_search_mode(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    _open_project_with_document(window, tmp_path, "Hello frustrating world.")

    window.viewer.setFocus()
    qtbot.waitUntil(lambda: window.viewer.hasFocus())

    QTest.keyClick(window.viewer, Qt.Key_Slash)
    QTest.keyClicks(window.viewer, "wor")
    QTest.keyClick(window.viewer, Qt.Key_Return)

    assert window.search_label.text() == "/wor"

    QTest.keyClick(window.viewer, Qt.Key_H)  # normal-mode motions don't clear it
    assert window.search_label.text() == "/wor"


def test_escape_during_search_reverts_the_persisted_search_label(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    _open_project_with_document(window, tmp_path, "Hello frustrating world.")

    window.viewer.setFocus()
    qtbot.waitUntil(lambda: window.viewer.hasFocus())

    QTest.keyClick(window.viewer, Qt.Key_Slash)
    QTest.keyClicks(window.viewer, "wor")
    QTest.keyClick(window.viewer, Qt.Key_Return)
    assert window.search_label.text() == "/wor"

    QTest.keyClick(window.viewer, Qt.Key_Slash)
    QTest.keyClicks(window.viewer, "xyz")
    assert window.search_label.text() == "/xyz"

    QTest.keyClick(window.viewer, Qt.Key_Escape)

    assert window.vim_mode_label.text() == ""
    assert window.search_label.text() == "/wor"  # reverts to the last committed pattern


def test_space_while_searching_is_added_to_the_pattern_instead_of_shifting_focus(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    _open_project_with_document(window, tmp_path, "Hello frustrating world.")

    window.viewer.setFocus()
    qtbot.waitUntil(lambda: window.viewer.hasFocus())

    QTest.keyClick(window.viewer, Qt.Key_Slash)
    QTest.keyClicks(window.viewer, "a b")

    assert window.viewer.hasFocus()
    assert window.search_label.text() == "/a b"


def test_n_after_search_enters_visual_mode_so_enter_codes_the_match(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    _open_project_with_document(window, tmp_path, "Hello frustrating world.")
    code = window.add_code("Frustration")

    _place_cursor(window, 0)
    window.viewer.setFocus()
    qtbot.waitUntil(lambda: window.viewer.hasFocus())

    QTest.keyClick(window.viewer, Qt.Key_Slash)
    QTest.keyClicks(window.viewer, "frustrating")
    QTest.keyClick(window.viewer, Qt.Key_Return)

    QTest.keyClick(window.viewer, Qt.Key_N)
    assert window.viewer.mode == VimTextViewer.VISUAL
    assert window.viewer.textCursor().selectedText() == "frustrating"

    window.code_tree.setCurrentItem(window._code_items_by_id[code.id])
    QTest.keyClick(window.viewer, Qt.Key_Return)

    segments = db.list_segments_for_document(window.conn, window._current_document_id)
    assert len(segments) == 1
    assert segments[0].code_id == code.id
    assert (segments[0].start_offset, segments[0].end_offset) == (6, 17)
    assert window.viewer.mode == VimTextViewer.NORMAL


def test_f_target_char_x_does_not_trigger_the_delete_segment_shortcut(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    content = "Hello frustrating world. Text here."
    _open_project_with_document(window, tmp_path, content)
    code = window.add_code("Frustration")
    window.apply_segment(code.id, 6, 17)  # "frustrating"

    _place_cursor(window, 10)  # inside the coded span
    window.viewer.setFocus()
    qtbot.waitUntil(lambda: window.viewer.hasFocus())

    QTest.keyClick(window.viewer, Qt.Key_F)
    QTest.keyClicks(window.viewer, "x")  # target char, not the delete-segment shortcut

    assert window.viewer.textCursor().position() == content.index("x")
    assert db.list_segments_for_document(window.conn, window._current_document_id) != []


def test_f_target_char_space_does_not_shift_focus_to_code_filter(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    _open_project_with_document(window, tmp_path, "Hello frustrating world.")

    _place_cursor(window, 0)
    window.viewer.setFocus()
    qtbot.waitUntil(lambda: window.viewer.hasFocus())

    QTest.keyClick(window.viewer, Qt.Key_F)
    QTest.keyClick(window.viewer, Qt.Key_Space)  # target char, not the code-filter shortcut

    assert window.viewer.textCursor().position() == 5
    assert window.viewer.hasFocus()


def test_i_enters_insert_mode_and_shows_label(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    _open_project_with_document(window, tmp_path)

    window.viewer.setFocus()
    qtbot.waitUntil(lambda: window.viewer.hasFocus())

    QTest.keyClick(window.viewer, Qt.Key_I)

    assert window.viewer.mode == VimTextViewer.INSERT
    assert window.vim_mode_label.text() == "-- INSERT --"
    assert window.insert_mode_button.isChecked()

    QTest.keyClick(window.viewer, Qt.Key_Escape)

    assert window.viewer.mode == VimTextViewer.NORMAL
    assert window.vim_mode_label.text() == ""
    assert not window.insert_mode_button.isChecked()


def test_insert_mode_button_toggles_insert_mode(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    _open_project_with_document(window, tmp_path)

    window.insert_mode_button.setChecked(True)
    qtbot.waitUntil(lambda: window.viewer.hasFocus())
    assert window.viewer.mode == VimTextViewer.INSERT

    window.insert_mode_button.setChecked(False)
    assert window.viewer.mode == VimTextViewer.NORMAL


def test_typing_in_insert_mode_persists_document_content(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    _open_project_with_document(window, tmp_path, "Hello world.")

    window.viewer.setFocus()
    qtbot.waitUntil(lambda: window.viewer.hasFocus())
    _place_cursor(window, 0)

    QTest.keyClick(window.viewer, Qt.Key_I)
    QTest.keyClicks(window.viewer, "Well, ")
    QTest.keyClick(window.viewer, Qt.Key_Escape)

    doc = db.get_document(window.conn, window._current_document_id)
    assert doc.content == "Well, Hello world."


def test_insert_before_segment_shifts_its_offsets(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    _open_project_with_document(window, tmp_path, "Hello frustrating world.")
    code = window.add_code("Frustration")
    window.apply_segment(code.id, 6, 17)  # "frustrating"

    window.viewer.setFocus()
    qtbot.waitUntil(lambda: window.viewer.hasFocus())
    _place_cursor(window, 0)

    QTest.keyClick(window.viewer, Qt.Key_I)
    QTest.keyClicks(window.viewer, "Say: ")  # 5 chars inserted before the segment
    QTest.keyClick(window.viewer, Qt.Key_Escape)

    segments = db.list_segments_for_document(window.conn, window._current_document_id)
    assert len(segments) == 1
    assert (segments[0].start_offset, segments[0].end_offset) == (11, 22)


def test_insert_inside_segment_extends_it(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    _open_project_with_document(window, tmp_path, "Hello frustrating world.")
    code = window.add_code("Frustration")
    window.apply_segment(code.id, 6, 17)  # "frustrating"

    window.viewer.setFocus()
    qtbot.waitUntil(lambda: window.viewer.hasFocus())
    _place_cursor(window, 10)  # inside the coded span

    QTest.keyClick(window.viewer, Qt.Key_I)
    QTest.keyClicks(window.viewer, "XX")
    QTest.keyClick(window.viewer, Qt.Key_Escape)

    segments = db.list_segments_for_document(window.conn, window._current_document_id)
    assert len(segments) == 1
    assert (segments[0].start_offset, segments[0].end_offset) == (6, 19)


def test_delete_before_segment_shifts_its_offsets_back(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    _open_project_with_document(window, tmp_path, "Hello frustrating world.")
    code = window.add_code("Frustration")
    window.apply_segment(code.id, 6, 17)  # "frustrating"

    window.viewer.setFocus()
    qtbot.waitUntil(lambda: window.viewer.hasFocus())
    _place_cursor(window, 5)  # right after "Hello"

    QTest.keyClick(window.viewer, Qt.Key_I)
    for _ in range(5):
        QTest.keyClick(window.viewer, Qt.Key_Backspace)  # deletes "Hello"
    QTest.keyClick(window.viewer, Qt.Key_Escape)

    assert window.viewer.toPlainText() == " frustrating world."
    segments = db.list_segments_for_document(window.conn, window._current_document_id)
    assert len(segments) == 1
    assert (segments[0].start_offset, segments[0].end_offset) == (1, 12)


def test_deleting_a_coded_span_removes_its_segment(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    _open_project_with_document(window, tmp_path, "Hello frustrating world.")
    code = window.add_code("Frustration")
    window.apply_segment(code.id, 6, 17)  # "frustrating"

    window.viewer.setFocus()
    qtbot.waitUntil(lambda: window.viewer.hasFocus())
    _place_cursor(window, 17)  # right after "frustrating"

    QTest.keyClick(window.viewer, Qt.Key_I)
    for _ in range(11):
        QTest.keyClick(window.viewer, Qt.Key_Backspace)  # deletes "frustrating"
    QTest.keyClick(window.viewer, Qt.Key_Escape)

    assert window.viewer.toPlainText() == "Hello  world."
    assert db.list_segments_for_document(window.conn, window._current_document_id) == []


def test_space_while_inserting_types_a_space_instead_of_shifting_focus(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    _open_project_with_document(window, tmp_path, "Helloworld.")

    window.viewer.setFocus()
    qtbot.waitUntil(lambda: window.viewer.hasFocus())
    _place_cursor(window, 5)

    QTest.keyClick(window.viewer, Qt.Key_I)
    QTest.keyClick(window.viewer, Qt.Key_Space)

    assert window.viewer.toPlainText() == "Hello world."
    assert window.viewer.hasFocus()


def test_enter_while_inserting_inserts_a_newline_instead_of_applying_a_code(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    _open_project_with_document(window, tmp_path, "Hello world.")
    window.add_code("Greeting")

    window.viewer.setFocus()
    qtbot.waitUntil(lambda: window.viewer.hasFocus())
    _place_cursor(window, 5)

    QTest.keyClick(window.viewer, Qt.Key_I)
    QTest.keyClick(window.viewer, Qt.Key_Return)

    assert window.viewer.toPlainText() == "Hello\n world."
    assert db.list_segments_for_document(window.conn, window._current_document_id) == []


def test_switching_documents_exits_insert_mode(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    window.create_project(tmp_path / "project.sqlite")
    (tmp_path / "a.txt").write_text("Content A here.", encoding="utf-8")
    (tmp_path / "b.txt").write_text("Content B here.", encoding="utf-8")
    window.import_document(tmp_path / "a.txt")
    window.import_document(tmp_path / "b.txt")

    window.document_list.setCurrentRow(0)
    window.viewer.setFocus()
    qtbot.waitUntil(lambda: window.viewer.hasFocus())
    QTest.keyClick(window.viewer, Qt.Key_I)
    assert window.viewer.mode == VimTextViewer.INSERT

    window.document_list.setCurrentRow(1)

    assert window.viewer.mode == VimTextViewer.NORMAL
    assert window.viewer.isReadOnly()


def test_f_target_char_return_does_not_apply_a_code(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    _open_project_with_document(window, tmp_path, "Hello frustrating world.")
    code = window.add_code("Frustration")

    QTest.keyClick(window.viewer, Qt.Key_V)
    for _ in range(4):
        QTest.keyClick(window.viewer, Qt.Key_L)
    window.viewer.setFocus()
    qtbot.waitUntil(lambda: window.viewer.hasFocus())
    window.code_tree.setCurrentItem(window._code_items_by_id[code.id])

    QTest.keyClick(window.viewer, Qt.Key_F)
    QTest.keyClick(window.viewer, Qt.Key_Return)  # target char, not the apply-code shortcut

    assert db.list_segments_for_document(window.conn, window._current_document_id) == []
