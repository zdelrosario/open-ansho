from PySide6.QtCore import Qt

from openansho import db
from openansho.ui.main_window import (
    CODE_SORT_ALL_DOCUMENTS,
    NEW_CODE_LABEL,
    NEW_CODE_MARKER,
    MainWindow,
)


def _focus_filter(window, qtbot):
    window.code_filter_input.setFocus()
    qtbot.waitUntil(lambda: window.code_filter_input.hasFocus())


def _set_sort_mode(window, mode):
    index = window.code_sort_combo.findData(mode)
    window.code_sort_combo.setCurrentIndex(index)


def test_placeholder_appears_when_focused_with_no_exact_match(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    window.create_project(tmp_path / "project.sqlite")
    window.add_code("Frustration")

    _focus_filter(window, qtbot)
    window.code_filter_input.setText("frus")

    assert window.code_tree.topLevelItem(0).text(0) == NEW_CODE_LABEL


def test_placeholder_absent_when_field_empty(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    window.create_project(tmp_path / "project.sqlite")
    window.add_code("Frustration")

    _focus_filter(window, qtbot)
    window.code_filter_input.setText("")

    assert window.code_tree.topLevelItemCount() == 1
    assert window.code_tree.topLevelItem(0).text(0) == "Frustration"


def test_placeholder_absent_on_exact_match(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    window.create_project(tmp_path / "project.sqlite")
    window.add_code("Frustration")

    _focus_filter(window, qtbot)
    window.code_filter_input.setText("Frustration")

    assert window.code_tree.topLevelItemCount() == 1
    assert window.code_tree.topLevelItem(0).text(0) == "Frustration"


def test_placeholder_absent_on_exact_match_case_insensitive(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    window.create_project(tmp_path / "project.sqlite")
    window.add_code("Frustration")

    _focus_filter(window, qtbot)
    window.code_filter_input.setText("frustration")

    assert window.code_tree.topLevelItemCount() == 1


def test_placeholder_absent_when_focus_leaves_the_filter_field(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    window.create_project(tmp_path / "project.sqlite")

    _focus_filter(window, qtbot)
    window.code_filter_input.setText("frus")
    assert window.code_tree.topLevelItem(0).text(0) == NEW_CODE_LABEL

    window.viewer.setFocus()
    qtbot.waitUntil(lambda: window.viewer.hasFocus())

    assert window.code_tree.topLevelItemCount() == 0


def test_placeholder_never_shows_without_ever_focusing_the_field(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.create_project(tmp_path / "project.sqlite")

    window.code_filter_input.setText("frus")

    assert window.code_tree.topLevelItemCount() == 0


def test_placeholder_stays_first_regardless_of_sort_order(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    window.create_project(tmp_path / "project.sqlite")
    window.add_code("Anger")
    window.add_code("Zeal")

    _set_sort_mode(window, CODE_SORT_ALL_DOCUMENTS)

    _focus_filter(window, qtbot)
    window.code_filter_input.setText("an")

    assert window.code_tree.topLevelItem(0).text(0) == NEW_CODE_LABEL


def test_arrow_keys_reach_the_placeholder(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    window.create_project(tmp_path / "project.sqlite")
    window.add_code("Frustration")

    _focus_filter(window, qtbot)
    window.code_filter_input.setText("frus")
    assert window.code_tree.currentItem().text(0) == "Frustration"

    window.code_filter_input.cyclePressed.emit(-1)
    assert window.code_tree.currentItem() is window._new_code_item

    window.code_filter_input.cyclePressed.emit(1)
    assert window.code_tree.currentItem().text(0) == "Frustration"


def test_placeholder_selection_survives_further_typing(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    window.create_project(tmp_path / "project.sqlite")
    window.add_code("Frustration")

    _focus_filter(window, qtbot)
    window.code_filter_input.setText("frus")
    window.code_filter_input.cyclePressed.emit(-1)
    assert window.code_tree.currentItem() is window._new_code_item

    window.code_filter_input.setText("frust")

    assert window.code_tree.currentItem() is window._new_code_item


def test_enter_on_placeholder_creates_a_new_code(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    window.create_project(tmp_path / "project.sqlite")
    window.add_code("Frustration")

    _focus_filter(window, qtbot)
    window.code_filter_input.setText("frus")
    window.code_filter_input.cyclePressed.emit(-1)
    assert window.code_tree.currentItem() is window._new_code_item

    window.code_filter_input.returnPressed.emit()

    names = sorted(code.name for code in db.list_codes(window.conn))
    assert names == ["Frustration", "frus"]
    assert window.code_filter_input.text() == ""
    assert window.code_tree.currentItem().text(0) == "frus"


def test_enter_on_placeholder_applies_to_viewer_selection(qtbot, tmp_path):
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

    _focus_filter(window, qtbot)
    window.code_filter_input.setText("frustrating")
    window.code_filter_input.cyclePressed.emit(-1)
    assert window.code_tree.currentItem() is window._new_code_item

    window.code_filter_input.returnPressed.emit()

    segments = db.list_segments_for_document(window.conn, window._current_document_id)
    assert len(segments) == 1
    assert segments[0].start_offset == 6
    assert segments[0].end_offset == 17
    created_code = db.get_code(window.conn, segments[0].code_id)
    assert created_code.name == "frustrating"
    qtbot.waitUntil(lambda: window.viewer.hasFocus())


def test_enter_on_placeholder_without_selection_keeps_focus_in_filter(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    window.create_project(tmp_path / "project.sqlite")
    window.add_code("Frustration")

    _focus_filter(window, qtbot)
    window.code_filter_input.setText("frus")
    window.code_filter_input.cyclePressed.emit(-1)
    assert window.code_tree.currentItem() is window._new_code_item

    window.code_filter_input.returnPressed.emit()

    assert window.code_filter_input.hasFocus()


def test_placeholder_does_not_create_a_code_until_enter_is_pressed(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    window.create_project(tmp_path / "project.sqlite")

    _focus_filter(window, qtbot)
    window.code_filter_input.setText("Anger")

    assert db.list_codes(window.conn) == []
    assert window.code_tree.topLevelItem(0).data(0, Qt.UserRole) == NEW_CODE_MARKER
