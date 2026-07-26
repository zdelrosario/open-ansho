import pytest

from opencoder.ui.main_window import MainWindow


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
        "opencoder.ui.main_window.QMessageBox.warning",
        lambda *args, **kwargs: shown.append(args),
    )

    window.code_tree.codeReparented.emit(grandparent.id, parent.id)

    assert shown
    assert window.code_tree.topLevelItemCount() == 1
    assert window.code_tree.topLevelItem(0).text(0) == "Emotions"
    assert window.code_tree.topLevelItem(0).child(0).text(0) == "Frustration"
