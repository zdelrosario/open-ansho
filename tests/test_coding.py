from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor

from openansho import db
from openansho.ui.main_window import BASE_COLOR_CLASSES
from openansho.ui.main_window import MainWindow


def _open_project_with_document(window, tmp_path, content="Hello frustrating world."):
    window.create_project(tmp_path / "project.sqlite")
    doc_path = tmp_path / "doc.txt"
    doc_path.write_text(content, encoding="utf-8")
    window.import_document(doc_path)
    window.document_list.setCurrentRow(0)
    return doc_path


def test_add_code_appears_in_list_with_base_color(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.create_project(tmp_path / "project.sqlite")

    code = window.add_code("Frustration")

    assert code.color in BASE_COLOR_CLASSES
    assert code.color_class == code.color
    assert window.code_tree.topLevelItemCount() == 1
    assert window.code_tree.topLevelItem(0).text(0) == "Frustration"


def test_root_codes_balance_across_base_color_classes(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.create_project(tmp_path / "project.sqlite")

    for i in range(len(BASE_COLOR_CLASSES)):
        window.add_code(f"Code {i}")

    counts = db.count_codes_by_color_class(window.conn)
    assert counts == {color_class: 1 for color_class in BASE_COLOR_CLASSES}


def test_child_code_inherits_parent_color_class_with_lighter_shade(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.create_project(tmp_path / "project.sqlite")

    parent = window.add_code("Emotions")
    child = window.add_code("Frustration", parent_id=parent.id)
    grandchild = window.add_code("Anger", parent_id=child.id)

    assert child.color_class == parent.color_class
    assert grandchild.color_class == parent.color_class
    assert child.color != parent.color
    assert grandchild.color != child.color


def test_apply_segment_creates_segment_and_highlight(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    _open_project_with_document(window, tmp_path)

    code = window.add_code("Frustration")
    window.apply_segment(code.id, 6, 16)  # "frustrating"

    segments = db.list_segments_for_document(window.conn, window._current_document_id)
    assert len(segments) == 1
    assert segments[0].code_id == code.id
    assert segments[0].start_offset == 6
    assert segments[0].end_offset == 16

    # Code highlights are painted separately (not via extraSelections), so
    # extraSelections() only ever holds the vim viewer's block cursor.
    assert len(window.viewer.extraSelections()) == 1
    assert len(window.viewer._code_highlights) == 1


def test_switching_documents_refreshes_highlights(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.create_project(tmp_path / "project.sqlite")

    (tmp_path / "a.txt").write_text("Content A is frustrating.", encoding="utf-8")
    (tmp_path / "b.txt").write_text("Content B is calm.", encoding="utf-8")
    window.import_document(tmp_path / "a.txt")
    window.import_document(tmp_path / "b.txt")

    code = window.add_code("Frustration")

    # Code highlights are painted separately (not via extraSelections), so
    # extraSelections() only ever holds the vim viewer's block cursor.
    window.document_list.setCurrentRow(0)
    window.apply_segment(code.id, 13, 24)
    assert len(window.viewer.extraSelections()) == 1
    assert len(window.viewer._code_highlights) == 1

    window.document_list.setCurrentRow(1)
    assert len(window.viewer.extraSelections()) == 1
    assert len(window.viewer._code_highlights) == 0

    window.document_list.setCurrentRow(0)
    assert len(window.viewer.extraSelections()) == 1
    assert len(window.viewer._code_highlights) == 1


def test_coding_an_already_coded_segment_adds_a_second_code(qtbot, tmp_path):
    """Simultaneous coding: applying a second code to an already-coded span
    must add a second segment row, not replace the first."""
    window = MainWindow()
    qtbot.addWidget(window)
    _open_project_with_document(window, tmp_path, content="Hello frustrating world.")

    outer = window.add_code("Outer")
    inner = window.add_code("Inner")
    window.apply_segment(outer.id, 6, 16)  # "frustrating"
    window.apply_segment(inner.id, 6, 16)  # same span, a second code

    segments = db.list_segments_for_document(window.conn, window._current_document_id)
    assert len(segments) == 2
    assert {s.code_id for s in segments} == {outer.id, inner.id}


def test_coded_segments_pane_shows_every_code_on_the_segment_at_the_cursor(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    _open_project_with_document(window, tmp_path, content="Hello frustrating world.")

    outer = window.add_code("Outer")
    inner = window.add_code("Inner")
    window.apply_segment(outer.id, 0, 24)  # "Hello frustrating world"
    window.apply_segment(inner.id, 6, 16)  # "frustrating", nested inside outer

    cursor = window.viewer.textCursor()
    cursor.setPosition(8)
    window.viewer.setTextCursor(cursor)

    # Cursor-driven grouping (see _on_viewer_cursor_moved) is normally
    # triggered by the viewer having real window focus; drive the render
    # directly here so the test doesn't depend on a shown top-level window.
    window._segments_panel_mode = "cursor"
    window._render_segments_panel()

    headers = [
        window.segment_list.item(i).text()
        for i in range(window.segment_list.count())
        if window.segment_list.item(i).data(Qt.UserRole)[0] == "code_header"
    ]
    assert set(headers) == {"Outer", "Inner"}


def test_remove_code_from_selection_only_deletes_that_codes_segment(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    _open_project_with_document(window, tmp_path, content="Hello frustrating world.")

    outer = window.add_code("Outer")
    inner = window.add_code("Inner")
    window.apply_segment(outer.id, 6, 16)
    window.apply_segment(inner.id, 6, 16)

    cursor = window.viewer.textCursor()
    cursor.setPosition(6)
    cursor.setPosition(16, QTextCursor.KeepAnchor)
    window.viewer.setTextCursor(cursor)

    window._remove_code_from_viewer_selection(inner.id)

    segments = db.list_segments_for_document(window.conn, window._current_document_id)
    assert len(segments) == 1
    assert segments[0].code_id == outer.id


def test_apply_code_button_noop_without_selection(qtbot, tmp_path, monkeypatch):
    window = MainWindow()
    qtbot.addWidget(window)
    _open_project_with_document(window, tmp_path)
    window.add_code("Frustration")
    window.code_tree.setCurrentItem(window.code_tree.topLevelItem(0))

    shown = []
    monkeypatch.setattr(
        "openansho.ui.main_window.QMessageBox.information",
        lambda *args, **kwargs: shown.append(args),
    )

    window.viewer.textCursor().clearSelection()
    window._on_apply_code()

    assert shown
    assert db.list_segments_for_document(window.conn, window._current_document_id) == []
