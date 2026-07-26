from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from opencoder import db
from opencoder.ui.main_window import MainWindow


def test_typing_highlights_the_single_match(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.create_project(tmp_path / "project.sqlite")
    frustration = window.add_code("Frustration")
    window.add_code("Reward")

    window.code_filter_input.setText("frus")

    current = window.code_tree.currentItem()
    assert current is not None
    assert current.text(0) == "Frustration"
    assert current.data(0, Qt.UserRole) == frustration.id


def test_clearing_filter_does_not_force_a_selection_change(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.create_project(tmp_path / "project.sqlite")
    window.add_code("Frustration")
    window.add_code("Reward")

    window.code_filter_input.setText("frus")
    selected_before = window.code_tree.currentItem()
    window.code_filter_input.setText("")

    assert window.code_tree.currentItem() is selected_before


def test_no_matches_clears_the_highlight(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.create_project(tmp_path / "project.sqlite")
    window.add_code("Frustration")

    window.code_filter_input.setText("zzz")

    assert window.code_tree.currentItem() is None


def test_down_arrow_cycles_to_next_match(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.create_project(tmp_path / "project.sqlite")
    window.add_code("Anger")
    window.add_code("Angst")
    window.add_code("Anxiety")

    window.code_filter_input.setText("an")
    assert window.code_tree.currentItem().text(0) == "Anger"

    window.code_filter_input.cyclePressed.emit(1)
    assert window.code_tree.currentItem().text(0) == "Angst"

    window.code_filter_input.cyclePressed.emit(1)
    assert window.code_tree.currentItem().text(0) == "Anxiety"

    window.code_filter_input.cyclePressed.emit(1)
    assert window.code_tree.currentItem().text(0) == "Anger"  # wraps around


def test_up_arrow_cycles_to_previous_match(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.create_project(tmp_path / "project.sqlite")
    window.add_code("Anger")
    window.add_code("Angst")

    window.code_filter_input.setText("an")
    assert window.code_tree.currentItem().text(0) == "Anger"

    window.code_filter_input.cyclePressed.emit(-1)
    assert window.code_tree.currentItem().text(0) == "Angst"  # wraps backward


def test_typing_preserves_cycled_selection_if_still_matching(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.create_project(tmp_path / "project.sqlite")
    window.add_code("Anger")
    window.add_code("Angst")
    window.add_code("Anxiety")

    window.code_filter_input.setText("an")
    window.code_filter_input.cyclePressed.emit(1)
    assert window.code_tree.currentItem().text(0) == "Angst"

    window._on_code_filter_changed("an")  # simulate re-filtering with the same query
    assert window.code_tree.currentItem().text(0) == "Angst"


def test_enter_applies_highlighted_code_to_viewer_selection(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.create_project(tmp_path / "project.sqlite")
    doc_path = tmp_path / "doc.txt"
    doc_path.write_text("Hello frustrating world.", encoding="utf-8")
    window.import_document(doc_path)
    window.document_list.setCurrentRow(0)

    code = window.add_code("Frustration")

    cursor = window.viewer.textCursor()
    cursor.setPosition(6)
    cursor.setPosition(17, cursor.MoveMode.KeepAnchor)
    window.viewer.setTextCursor(cursor)

    window.code_filter_input.setText("frus")
    window.code_filter_input.returnPressed.emit()

    segments = db.list_segments_for_document(window.conn, window._current_document_id)
    assert len(segments) == 1
    assert segments[0].code_id == code.id
    assert segments[0].start_offset == 6
    assert segments[0].end_offset == 17
    # No new code should have been created.
    assert window.code_tree.topLevelItemCount() == 1


def test_enter_applies_cycled_code_not_just_first_match(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.create_project(tmp_path / "project.sqlite")
    doc_path = tmp_path / "doc.txt"
    doc_path.write_text("Hello frustrating world.", encoding="utf-8")
    window.import_document(doc_path)
    window.document_list.setCurrentRow(0)

    window.add_code("Anger")
    reward = window.add_code("Angst-Reward")  # deliberately matches "an" too

    window.code_filter_input.setText("an")
    window.code_filter_input.cyclePressed.emit(1)
    assert window.code_tree.currentItem().text(0) == "Angst-Reward"

    cursor = window.viewer.textCursor()
    cursor.setPosition(6)
    cursor.setPosition(17, cursor.MoveMode.KeepAnchor)
    window.viewer.setTextCursor(cursor)

    window.code_filter_input.returnPressed.emit()

    segments = db.list_segments_for_document(window.conn, window._current_document_id)
    assert len(segments) == 1
    assert segments[0].code_id == reward.id


def test_enter_without_viewer_selection_just_selects_the_code(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.create_project(tmp_path / "project.sqlite")
    window.add_code("Frustration")

    window.code_filter_input.setText("frus")
    window.code_filter_input.returnPressed.emit()

    assert window.code_tree.topLevelItemCount() == 1
    assert window.code_tree.currentItem().text(0) == "Frustration"


def test_enter_with_no_matches_still_creates_new_code(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.create_project(tmp_path / "project.sqlite")
    window.add_code("Reward")

    window.code_filter_input.setText("Frustration")
    window.code_filter_input.returnPressed.emit()

    assert window.code_tree.topLevelItemCount() == 2
    assert window.code_filter_input.text() == ""


def test_enter_applying_existing_code_returns_focus_to_viewer(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    window.create_project(tmp_path / "project.sqlite")
    doc_path = tmp_path / "doc.txt"
    doc_path.write_text("Hello frustrating world.", encoding="utf-8")
    window.import_document(doc_path)
    window.document_list.setCurrentRow(0)
    window.add_code("Frustration")

    cursor = window.viewer.textCursor()
    cursor.setPosition(6)
    cursor.setPosition(17, cursor.MoveMode.KeepAnchor)
    window.viewer.setTextCursor(cursor)

    window.code_filter_input.setFocus()
    qtbot.waitUntil(lambda: window.code_filter_input.hasFocus())
    window.code_filter_input.setText("frus")
    window.code_filter_input.returnPressed.emit()

    qtbot.waitUntil(lambda: window.viewer.hasFocus())


def test_enter_creating_new_code_applies_to_selection_and_returns_focus(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    window.create_project(tmp_path / "project.sqlite")
    doc_path = tmp_path / "doc.txt"
    doc_path.write_text("Hello frustrating world.", encoding="utf-8")
    window.import_document(doc_path)
    window.document_list.setCurrentRow(0)

    cursor = window.viewer.textCursor()
    cursor.setPosition(6)
    cursor.setPosition(17, cursor.MoveMode.KeepAnchor)
    window.viewer.setTextCursor(cursor)

    window.code_filter_input.setFocus()
    qtbot.waitUntil(lambda: window.code_filter_input.hasFocus())
    window.code_filter_input.setText("Frustration")
    window.code_filter_input.returnPressed.emit()

    segments = db.list_segments_for_document(window.conn, window._current_document_id)
    assert len(segments) == 1
    assert segments[0].start_offset == 6
    assert segments[0].end_offset == 17
    assert window.code_tree.topLevelItemCount() == 1

    qtbot.waitUntil(lambda: window.viewer.hasFocus())


def test_enter_creating_new_code_without_selection_does_not_steal_focus(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    window.create_project(tmp_path / "project.sqlite")

    window.code_filter_input.setFocus()
    qtbot.waitUntil(lambda: window.code_filter_input.hasFocus())
    window.code_filter_input.setText("Frustration")
    window.code_filter_input.returnPressed.emit()

    assert window.code_tree.topLevelItemCount() == 1
    assert window.code_filter_input.hasFocus()


def test_space_selects_all_text_in_code_filter_input(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    window.create_project(tmp_path / "project.sqlite")
    window.code_filter_input.setText("existing")

    window.viewer.setFocus()
    qtbot.waitUntil(lambda: window.viewer.hasFocus())

    QTest.keyClick(window.viewer, Qt.Key_Space)

    qtbot.waitUntil(lambda: window.code_filter_input.hasFocus())
    assert window.code_filter_input.selectedText() == "existing"
