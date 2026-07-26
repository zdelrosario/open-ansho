from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtTest import QTest

from opencoder import db
from opencoder.ui.main_window import MainWindow
from opencoder.ui.vim_viewer import VimTextViewer


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

    # code highlight + vim cursor block should coexist
    assert len(window.viewer.extraSelections()) == 2


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


def test_x_does_nothing_in_visual_mode(qtbot, tmp_path):
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
