from openansho.ui.main_window import MainWindow


def test_typing_filters_tree_by_substring(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.create_project(tmp_path / "project.sqlite")
    window.add_code("Frustration")
    window.add_code("Reward")

    window.code_filter_input.setText("frus")

    items = {
        window.code_tree.topLevelItem(i).text(0): window.code_tree.topLevelItem(i)
        for i in range(window.code_tree.topLevelItemCount())
    }
    assert items["Frustration"].isHidden() is False
    assert items["Reward"].isHidden() is True


def test_clearing_filter_shows_all_codes_again(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.create_project(tmp_path / "project.sqlite")
    window.add_code("Frustration")
    window.add_code("Reward")

    window.code_filter_input.setText("frus")
    window.code_filter_input.setText("")

    items = [window.code_tree.topLevelItem(i) for i in range(window.code_tree.topLevelItemCount())]
    assert all(not item.isHidden() for item in items)


def test_filter_keeps_parent_visible_when_child_matches(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.create_project(tmp_path / "project.sqlite")
    parent = window.add_code("Emotions")
    window.add_code("Frustration", parent_id=parent.id)
    window.add_code("Calm", parent_id=parent.id)

    window.code_filter_input.setText("frus")

    parent_item = window.code_tree.topLevelItem(0)
    assert parent_item.text(0) == "Emotions"
    assert parent_item.isHidden() is False
    assert parent_item.isExpanded() is True

    child_items = {parent_item.child(i).text(0): parent_item.child(i) for i in range(parent_item.childCount())}
    assert child_items["Frustration"].isHidden() is False
    assert child_items["Calm"].isHidden() is True


def test_enter_creates_new_code_when_no_exact_match(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.create_project(tmp_path / "project.sqlite")

    window.code_filter_input.setText("Frustration")
    window.code_filter_input.returnPressed.emit()

    assert window.code_tree.topLevelItemCount() == 1
    assert window.code_tree.topLevelItem(0).text(0) == "Frustration"
    assert window.code_filter_input.text() == ""


def test_enter_selects_created_code(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.create_project(tmp_path / "project.sqlite")

    window.code_filter_input.setText("Frustration")
    window.code_filter_input.returnPressed.emit()

    assert window.code_tree.currentItem() is not None
    assert window.code_tree.currentItem().text(0) == "Frustration"


def test_enter_does_not_create_duplicate_for_exact_match(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.create_project(tmp_path / "project.sqlite")
    window.add_code("Frustration")

    window.code_filter_input.setText("Frustration")
    window.code_filter_input.returnPressed.emit()

    assert window.code_tree.topLevelItemCount() == 1


def test_enter_exact_match_is_case_insensitive(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.create_project(tmp_path / "project.sqlite")
    window.add_code("Frustration")

    window.code_filter_input.setText("frustration")
    window.code_filter_input.returnPressed.emit()

    assert window.code_tree.topLevelItemCount() == 1


def test_enter_with_empty_text_does_nothing(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.create_project(tmp_path / "project.sqlite")

    window.code_filter_input.setText("   ")
    window.code_filter_input.returnPressed.emit()

    assert window.code_tree.topLevelItemCount() == 0
