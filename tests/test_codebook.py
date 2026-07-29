import pytest
from PySide6.QtCore import Qt

from openansho import db
from openansho.ui.main_window import BASE_COLOR_CLASSES, MainWindow


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


def test_edit_code_description_updates_tooltip(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.create_project(tmp_path / "project.sqlite")

    code = window.add_code("Frustration")
    item = window.code_tree.topLevelItem(0)
    assert item.toolTip(0) == "(No code description)"

    updated = window.edit_code_description(code.id, "Expressions of frustration.")

    assert updated.description == "Expressions of frustration."
    item = window.code_tree.topLevelItem(0)
    assert item.toolTip(0) == "Expressions of frustration."

    window.edit_code_description(code.id, "")
    item = window.code_tree.topLevelItem(0)
    assert item.toolTip(0) == "(No code description)"


def test_set_code_base_color_assigns_chosen_class(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.create_project(tmp_path / "project.sqlite")

    code = window.add_code("Emotions")
    other_class = next(c for c in BASE_COLOR_CLASSES if c != code.color_class)

    updated = window.set_code_base_color(code.id, other_class)

    assert updated.color_class == other_class
    assert updated.color == other_class


def test_set_code_base_color_recolors_descendants(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.create_project(tmp_path / "project.sqlite")

    parent = window.add_code("Emotions")
    child = window.add_code("Frustration", parent_id=parent.id)
    grandchild = window.add_code("Anger", parent_id=child.id)
    other_class = next(c for c in BASE_COLOR_CLASSES if c != parent.color_class)

    window.set_code_base_color(parent.id, other_class)

    updated_child = db.get_code(window.conn, child.id)
    updated_grandchild = db.get_code(window.conn, grandchild.id)
    assert updated_child.color_class == other_class
    assert updated_grandchild.color_class == other_class
    assert updated_child.color != other_class  # lightened, not the raw base color
    assert updated_grandchild.color != updated_child.color


def test_set_code_base_color_rejects_child_codes(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.create_project(tmp_path / "project.sqlite")

    parent = window.add_code("Emotions")
    child = window.add_code("Frustration", parent_id=parent.id)

    with pytest.raises(ValueError):
        window.set_code_base_color(child.id, BASE_COLOR_CLASSES[0])


def test_set_code_base_color_rejects_unknown_class(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.create_project(tmp_path / "project.sqlite")

    code = window.add_code("Emotions")

    with pytest.raises(ValueError):
        window.set_code_base_color(code.id, "#123456")


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
    assert len(window.viewer._code_highlights) == 1

    window.delete_code(code.id)

    assert len(window.viewer._code_highlights) == 0
    assert len(window.viewer.extraSelections()) == 1  # just the block cursor


def test_merge_codes_recodes_segments_and_removes_merged_code(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    _open_project_with_document(window, tmp_path, "Hello frustrating world.")

    keep = window.add_code("Anger")
    merge = window.add_code("Frustration")
    window.apply_segment(merge.id, 6, 17)  # "frustrating"

    window.merge_codes(keep.id, merge.id)

    assert db.get_code(window.conn, merge.id) is None
    assert window.code_tree.topLevelItemCount() == 1
    assert window.code_tree.topLevelItem(0).data(0, Qt.UserRole) == keep.id
    segments = db.list_segments_for_code(window.conn, keep.id)
    assert len(segments) == 1


def test_merge_codes_reparents_children_to_kept_code(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.create_project(tmp_path / "project.sqlite")

    keep = window.add_code("Anger")
    merge = window.add_code("Frustration")
    child = window.add_code("Mild Frustration", parent_id=merge.id)

    window.merge_codes(keep.id, merge.id)

    keep_item = window.code_tree.topLevelItem(0)
    assert keep_item.data(0, Qt.UserRole) == keep.id
    assert keep_item.childCount() == 1
    assert keep_item.child(0).data(0, Qt.UserRole) == child.id


def test_merge_codes_rejects_merging_a_code_into_itself(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.create_project(tmp_path / "project.sqlite")

    code = window.add_code("Anger")

    with pytest.raises(ValueError):
        window.merge_codes(code.id, code.id)


def test_merge_codes_rejects_keeping_a_descendant_of_the_merged_code(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.create_project(tmp_path / "project.sqlite")

    merge = window.add_code("Emotions")
    keep = window.add_code("Frustration", parent_id=merge.id)

    with pytest.raises(ValueError):
        window.merge_codes(keep.id, merge.id)


def test_code_has_other_user_segments_ignores_own_and_blank_creators(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    _open_project_with_document(window, tmp_path, "Hello frustrating world.")
    window.username = "alice"

    code = window.add_code("Frustration")
    assert window._code_has_other_user_segments(code.id) is False

    db.create_segment(window.conn, window._current_document_id, code.id, 0, 5, created_by="alice")
    assert window._code_has_other_user_segments(code.id) is False

    db.create_segment(window.conn, window._current_document_id, code.id, 6, 17, created_by="bob")
    assert window._code_has_other_user_segments(code.id) is True


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
