from PySide6.QtCore import Qt

from opencoder.ui.main_window import MainWindow


def _open_project_with_document(window, tmp_path, content="Hello frustrating world."):
    window.create_project(tmp_path / "project.sqlite")
    doc_path = tmp_path / "doc.txt"
    doc_path.write_text(content, encoding="utf-8")
    window.import_document(doc_path)
    window.document_list.setCurrentRow(0)
    return doc_path


def test_child_code_nests_under_parent_in_tree(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.create_project(tmp_path / "project.sqlite")

    parent = window.add_code("Emotions")
    child = window.add_code("Frustration", parent_id=parent.id)

    assert window.code_tree.topLevelItemCount() == 1
    parent_item = window.code_tree.topLevelItem(0)
    assert parent_item.text(0) == "Emotions"
    assert parent_item.childCount() == 1
    assert parent_item.child(0).text(0) == "Frustration"
    assert parent_item.child(0).data(0, Qt.UserRole) == child.id


def test_rename_code_updates_tree_label(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.create_project(tmp_path / "project.sqlite")

    code = window.add_code("Frustation")  # typo on purpose
    window.rename_code(code.id, "Frustration")

    assert window.code_tree.topLevelItemCount() == 1
    assert window.code_tree.topLevelItem(0).text(0) == "Frustration"


def test_delete_code_reparents_children_in_tree(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.create_project(tmp_path / "project.sqlite")

    grandparent = window.add_code("Emotions")
    parent = window.add_code("Frustration", parent_id=grandparent.id)
    child = window.add_code("Anger", parent_id=parent.id)

    window.delete_code(parent.id)

    assert window.code_tree.topLevelItemCount() == 1
    grandparent_item = window.code_tree.topLevelItem(0)
    assert grandparent_item.text(0) == "Emotions"
    assert grandparent_item.childCount() == 1
    assert grandparent_item.child(0).data(0, Qt.UserRole) == child.id


def test_delete_root_code_makes_children_new_roots(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.create_project(tmp_path / "project.sqlite")

    parent = window.add_code("Emotions")
    child = window.add_code("Frustration", parent_id=parent.id)

    window.delete_code(parent.id)

    assert window.code_tree.topLevelItemCount() == 1
    assert window.code_tree.topLevelItem(0).data(0, Qt.UserRole) == child.id
    assert window.code_tree.topLevelItem(0).childCount() == 0


def test_delete_code_removes_its_highlight_from_the_viewer(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    _open_project_with_document(window, tmp_path, "Hello frustrating world.")

    code = window.add_code("Frustration")
    window.apply_segment(code.id, 6, 17)
    assert len(window.viewer.extraSelections()) == 2  # highlight + block cursor

    window.delete_code(code.id)

    assert len(window.viewer.extraSelections()) == 1  # just the block cursor now


def test_segment_list_populates_for_selected_code(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    _open_project_with_document(window, tmp_path, "Hello frustrating world.")

    code = window.add_code("Frustration")
    window.apply_segment(code.id, 6, 17)  # "frustrating"

    window.code_tree.setCurrentItem(window.code_tree.topLevelItem(0))

    assert window.segment_list.count() == 1
    assert "frustrating" in window.segment_list.item(0).text()
    assert "doc.txt" in window.segment_list.item(0).text()


def test_segment_list_updates_immediately_after_applying_new_segment(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    _open_project_with_document(window, tmp_path, "Hello frustrating world.")

    code = window.add_code("Frustration")
    window.code_tree.setCurrentItem(window.code_tree.topLevelItem(0))
    assert window.segment_list.count() == 0

    window.apply_segment(code.id, 6, 17)
    assert window.segment_list.count() == 1


def test_double_click_segment_selects_document_and_range(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.create_project(tmp_path / "project.sqlite")
    (tmp_path / "a.txt").write_text("Content A", encoding="utf-8")
    (tmp_path / "b.txt").write_text("Hello frustrating world.", encoding="utf-8")
    window.import_document(tmp_path / "a.txt")
    window.import_document(tmp_path / "b.txt")

    code = window.add_code("Frustration")
    window.document_list.setCurrentRow(1)
    window.apply_segment(code.id, 6, 17)

    window.document_list.setCurrentRow(0)
    assert window._current_document_id is not None

    window.code_tree.setCurrentItem(window.code_tree.topLevelItem(0))
    window._on_segment_activated(window.segment_list.item(0))

    assert window.document_list.currentItem().text() == "b.txt"
    cursor = window.viewer.textCursor()
    assert cursor.selectedText() == "frustrating"
