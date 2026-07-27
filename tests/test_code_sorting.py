from PySide6.QtCore import Qt

from openansho.ui.main_window import (
    CODE_SORT_ALL_DOCUMENTS,
    CODE_SORT_CURRENT_DOCUMENT,
    MainWindow,
)


def _open_project_with_document(window, tmp_path, name="doc.txt", content="Hello frustrating world."):
    doc_path = tmp_path / name
    doc_path.write_text(content, encoding="utf-8")
    window.import_document(doc_path)
    return doc_path


def _set_sort_mode(window, mode):
    index = window.code_sort_combo.findData(mode)
    window.code_sort_combo.setCurrentIndex(index)


def _top_level_names(window):
    return [
        window.code_tree.topLevelItem(i).text(0)
        for i in range(window.code_tree.topLevelItemCount())
    ]


def test_codes_default_to_alphabetical_order(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.create_project(tmp_path / "project.sqlite")

    window.add_code("Reward")
    window.add_code("Anger")
    window.add_code("Motivation")

    assert _top_level_names(window) == ["Anger", "Motivation", "Reward"]


def test_child_codes_are_alphabetical_within_their_parent(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.create_project(tmp_path / "project.sqlite")

    parent = window.add_code("Emotions")
    window.add_code("Reward", parent_id=parent.id)
    window.add_code("Anger", parent_id=parent.id)

    parent_item = window.code_tree.topLevelItem(0)
    child_names = [parent_item.child(i).text(0) for i in range(parent_item.childCount())]
    assert child_names == ["Anger", "Reward"]


def test_sort_by_current_document_count_orders_root_codes(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.create_project(tmp_path / "project.sqlite")
    _open_project_with_document(window, tmp_path)
    window.document_list.setCurrentRow(0)

    anger = window.add_code("Anger")
    reward = window.add_code("Reward")
    window.add_code("Motivation")

    window.apply_segment(reward.id, 0, 5)
    window.apply_segment(reward.id, 6, 17)
    window.apply_segment(anger.id, 6, 17)

    _set_sort_mode(window, CODE_SORT_CURRENT_DOCUMENT)

    assert _top_level_names(window) == ["Reward", "Anger", "Motivation"]


def test_sort_by_all_documents_count_uses_totals_across_documents(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.create_project(tmp_path / "project.sqlite")
    _open_project_with_document(window, tmp_path, "a.txt", "Hello frustrating world.")
    _open_project_with_document(window, tmp_path, "b.txt", "Hello frustrating world.")

    anger = window.add_code("Anger")
    reward = window.add_code("Reward")

    window.document_list.setCurrentRow(0)
    window.apply_segment(anger.id, 0, 5)

    window.document_list.setCurrentRow(1)
    window.apply_segment(reward.id, 0, 5)
    window.apply_segment(reward.id, 6, 17)

    _set_sort_mode(window, CODE_SORT_ALL_DOCUMENTS)

    assert _top_level_names(window) == ["Reward", "Anger"]


def test_segment_count_label_shows_current_over_total(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.create_project(tmp_path / "project.sqlite")
    _open_project_with_document(window, tmp_path, "a.txt", "Hello frustrating world.")
    _open_project_with_document(window, tmp_path, "b.txt", "Hello frustrating world.")

    code = window.add_code("Frustration")

    window.document_list.setCurrentRow(0)
    window.apply_segment(code.id, 6, 17)

    window.document_list.setCurrentRow(1)
    window.apply_segment(code.id, 6, 17)
    window.apply_segment(code.id, 0, 5)

    item = window._code_items_by_id[code.id]
    assert item.text(1) == "2/3"

    window.document_list.setCurrentRow(0)
    item = window._code_items_by_id[code.id]
    assert item.text(1) == "1/3"


def test_deleting_a_segment_updates_the_count_label(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.create_project(tmp_path / "project.sqlite")
    _open_project_with_document(window, tmp_path)
    window.document_list.setCurrentRow(0)

    code = window.add_code("Frustration")
    window.apply_segment(code.id, 6, 17)
    assert window._code_items_by_id[code.id].text(1) == "1/1"

    cursor = window.viewer.textCursor()
    cursor.setPosition(10)
    window.viewer.setTextCursor(cursor)
    window._delete_segments_at_cursor()

    assert window._code_items_by_id[code.id].text(1) == "0/0"


def test_changing_sort_mode_preserves_current_selection(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.create_project(tmp_path / "project.sqlite")

    window.add_code("Reward")
    window.add_code("Anger")

    window._select_code(window.add_code("Motivation").id)
    selected_id = window.code_tree.currentItem().data(0, Qt.UserRole)

    _set_sort_mode(window, CODE_SORT_ALL_DOCUMENTS)

    assert window.code_tree.currentItem() is not None
    assert window.code_tree.currentItem().data(0, Qt.UserRole) == selected_id
