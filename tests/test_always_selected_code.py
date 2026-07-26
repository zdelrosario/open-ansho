from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtTest import QTest

from opencoder.ui.main_window import MainWindow


def _open_project_with_document(window, tmp_path, content="Hello frustrating world."):
    window.create_project(tmp_path / "project.sqlite")
    doc_path = tmp_path / "doc.txt"
    doc_path.write_text(content, encoding="utf-8")
    window.import_document(doc_path)
    window.document_list.setCurrentRow(0)
    return doc_path


def _select_viewer_text(window, start, end):
    cursor = window.viewer.textCursor()
    cursor.setPosition(start)
    cursor.setPosition(end, QTextCursor.KeepAnchor)
    window.viewer.setTextCursor(cursor)


def test_selecting_viewer_text_auto_selects_a_code_with_empty_filter(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    _open_project_with_document(window, tmp_path)
    window.add_code("Frustration")
    window.add_code("Reward")
    assert window.code_tree.currentItem() is None

    _select_viewer_text(window, 6, 17)

    assert window.code_tree.currentItem() is not None
    assert window.code_tree.currentItem().text(0) == "Frustration"


def test_selecting_viewer_text_keeps_an_existing_selection(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    _open_project_with_document(window, tmp_path)
    window.add_code("Frustration")
    reward = window.add_code("Reward")
    window._select_code(reward.id)

    _select_viewer_text(window, 6, 17)

    assert window.code_tree.currentItem().text(0) == "Reward"


def test_clearing_viewer_selection_clears_the_code_selection(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    _open_project_with_document(window, tmp_path)
    window.add_code("Frustration")

    _select_viewer_text(window, 6, 17)
    assert window.code_tree.currentItem() is not None

    cursor = window.viewer.textCursor()
    cursor.clearSelection()
    window.viewer.setTextCursor(cursor)

    assert window.code_tree.currentItem() is None


def test_cycling_works_with_empty_filter_text(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.create_project(tmp_path / "project.sqlite")
    window.add_code("Anger")
    window.add_code("Reward")

    assert window.code_filter_input.text() == ""
    window.code_filter_input.cyclePressed.emit(1)
    assert window.code_tree.currentItem().text(0) == "Anger"

    window.code_filter_input.cyclePressed.emit(1)
    assert window.code_tree.currentItem().text(0) == "Reward"

    window.code_filter_input.cyclePressed.emit(1)
    assert window.code_tree.currentItem().text(0) == "Anger"  # wraps around


def test_spacebar_focuses_filter_field_from_elsewhere(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    _open_project_with_document(window, tmp_path)
    window.add_code("Frustration")

    window.document_list.setFocus()
    qtbot.waitUntil(lambda: window.document_list.hasFocus())

    QTest.keyClick(window.document_list, Qt.Key_Space)

    assert window.code_filter_input.hasFocus()


def test_spacebar_in_filter_field_types_a_space_instead_of_refocusing(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    window.create_project(tmp_path / "project.sqlite")

    window.code_filter_input.setFocus()
    qtbot.waitUntil(lambda: window.code_filter_input.hasFocus())
    window.code_filter_input.setText("foo")

    QTest.keyClick(window.code_filter_input, Qt.Key_Space)

    assert window.code_filter_input.text() == "foo "
    assert window.code_filter_input.hasFocus()


def test_arrow_keys_cycle_code_while_focus_stays_on_viewer(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    _open_project_with_document(window, tmp_path)
    window.add_code("Anger")
    window.add_code("Angst")

    window.viewer.setFocus()
    qtbot.waitUntil(lambda: window.viewer.hasFocus())
    _select_viewer_text(window, 6, 17)

    assert window.code_tree.currentItem().text(0) == "Anger"

    QTest.keyClick(window.viewer, Qt.Key_Down)
    assert window.code_tree.currentItem().text(0) == "Angst"
    assert window.viewer.hasFocus()

    QTest.keyClick(window.viewer, Qt.Key_Up)
    assert window.code_tree.currentItem().text(0) == "Anger"


def test_arrow_keys_on_viewer_do_not_collapse_the_text_selection(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    _open_project_with_document(window, tmp_path)
    window.add_code("Anger")
    window.add_code("Angst")

    window.viewer.setFocus()
    qtbot.waitUntil(lambda: window.viewer.hasFocus())
    _select_viewer_text(window, 6, 17)

    QTest.keyClick(window.viewer, Qt.Key_Down)

    assert window.viewer.textCursor().hasSelection()
    assert window.viewer.textCursor().selectedText() == "frustrating"


def test_arrow_keys_on_viewer_do_nothing_without_a_selection(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    _open_project_with_document(window, tmp_path)
    window.add_code("Anger")
    window.add_code("Angst")

    window.viewer.setFocus()
    qtbot.waitUntil(lambda: window.viewer.hasFocus())
    assert not window.viewer.textCursor().hasSelection()
    assert window.code_tree.currentItem() is None

    QTest.keyClick(window.viewer, Qt.Key_Down)

    assert window.code_tree.currentItem() is None
