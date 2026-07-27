import pytest
from PySide6.QtGui import QColor

from openansho import db
from openansho.ui.main_window import MainWindow


def test_reparent_code_moves_top_level_code_under_new_parent(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.create_project(tmp_path / "project.sqlite")

    emotions = window.add_code("Emotions")
    frustration = window.add_code("Frustration")

    window.reparent_code(frustration.id, emotions.id)

    parent_item = window.code_tree.topLevelItem(0)
    assert parent_item.text(0) == "Emotions"
    assert parent_item.childCount() == 1
    assert parent_item.child(0).text(0) == "Frustration"


def test_reparent_code_to_none_makes_it_top_level_again(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.create_project(tmp_path / "project.sqlite")

    emotions = window.add_code("Emotions")
    frustration = window.add_code("Frustration", parent_id=emotions.id)

    window.reparent_code(frustration.id, None)

    assert window.code_tree.topLevelItemCount() == 2
    top_level_names = {
        window.code_tree.topLevelItem(i).text(0) for i in range(window.code_tree.topLevelItemCount())
    }
    assert top_level_names == {"Emotions", "Frustration"}


def test_reparent_code_recolors_to_match_new_parent(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.create_project(tmp_path / "project.sqlite")

    emotions = window.add_code("Emotions")
    reactions = window.add_code("Reactions")
    frustration = window.add_code("Frustration")

    window.reparent_code(frustration.id, emotions.id)

    moved = db.get_code(window.conn, frustration.id)
    assert moved.color_class == emotions.color_class
    assert moved.color != emotions.color

    window.reparent_code(frustration.id, reactions.id)

    moved = db.get_code(window.conn, frustration.id)
    assert moved.color_class == reactions.color_class
    assert moved.color != reactions.color


def test_reparent_code_updates_viewer_highlight_color(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.create_project(tmp_path / "project.sqlite")
    doc_path = tmp_path / "doc.txt"
    doc_path.write_text("Hello frustrating world.", encoding="utf-8")
    window.import_document(doc_path)
    window.document_list.setCurrentRow(0)

    emotions = window.add_code("Emotions")
    frustration = window.add_code("Frustration")
    window.apply_segment(frustration.id, 6, 16)  # "frustrating"

    window.reparent_code(frustration.id, emotions.id)

    moved = db.get_code(window.conn, frustration.id)
    highlight = window.viewer._code_highlights[0]
    expected = QColor(moved.color)
    expected.setAlpha(highlight.color.alpha())
    assert highlight.color == expected


def test_reparent_code_to_none_reassigns_a_base_color_class(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.create_project(tmp_path / "project.sqlite")

    emotions = window.add_code("Emotions")
    frustration = window.add_code("Frustration", parent_id=emotions.id)

    window.reparent_code(frustration.id, None)

    moved = db.get_code(window.conn, frustration.id)
    assert moved.color_class == moved.color


def test_reparent_code_recolors_descendants(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.create_project(tmp_path / "project.sqlite")

    emotions = window.add_code("Emotions")
    grandparent = window.add_code("Grandparent")
    parent = window.add_code("Parent", parent_id=grandparent.id)
    child = window.add_code("Child", parent_id=parent.id)

    window.reparent_code(grandparent.id, emotions.id)

    moved_parent = db.get_code(window.conn, parent.id)
    moved_child = db.get_code(window.conn, child.id)
    assert moved_parent.color_class == emotions.color_class
    assert moved_child.color_class == emotions.color_class
    assert moved_child.color != moved_parent.color


def test_reparent_code_rejects_self_parenting(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.create_project(tmp_path / "project.sqlite")
    code = window.add_code("Emotions")

    with pytest.raises(ValueError):
        window.reparent_code(code.id, code.id)


def test_reparent_code_rejects_moving_under_own_descendant(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.create_project(tmp_path / "project.sqlite")

    grandparent = window.add_code("Emotions")
    parent = window.add_code("Frustration", parent_id=grandparent.id)
    child = window.add_code("Anger", parent_id=parent.id)

    with pytest.raises(ValueError):
        window.reparent_code(grandparent.id, child.id)


def test_on_code_reparented_signal_updates_db(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.create_project(tmp_path / "project.sqlite")

    emotions = window.add_code("Emotions")
    frustration = window.add_code("Frustration")

    window.code_tree.codeReparented.emit(frustration.id, emotions.id)

    parent_item = window.code_tree.topLevelItem(0)
    assert parent_item.childCount() == 1
    assert parent_item.child(0).text(0) == "Frustration"


def test_on_code_reparented_signal_reverts_tree_on_invalid_move(qtbot, tmp_path, monkeypatch):
    window = MainWindow()
    qtbot.addWidget(window)
    window.create_project(tmp_path / "project.sqlite")

    grandparent = window.add_code("Emotions")
    parent = window.add_code("Frustration", parent_id=grandparent.id)

    shown = []
    monkeypatch.setattr(
        "openansho.ui.main_window.QMessageBox.warning",
        lambda *args, **kwargs: shown.append(args),
    )

    window.code_tree.codeReparented.emit(grandparent.id, parent.id)

    assert shown
    assert window.code_tree.topLevelItemCount() == 1
    assert window.code_tree.topLevelItem(0).text(0) == "Emotions"
    assert window.code_tree.topLevelItem(0).child(0).text(0) == "Frustration"
