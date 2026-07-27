from openansho.ui.main_window import MainWindow


def test_focusing_a_pane_marks_only_that_pane(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()

    window.viewer.setFocus()
    qtbot.waitUntil(lambda: window.viewer.hasFocus())

    assert window.viewer.property("focused") is True
    assert window.document_list.property("focused") is not True
    assert window.code_tree.property("focused") is not True
    assert window.segment_list.property("focused") is not True


def test_focusing_a_widget_inside_the_codebook_does_not_mark_the_code_tree(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()

    window.code_filter_input.setFocus()
    qtbot.waitUntil(lambda: window.code_filter_input.hasFocus())

    assert window.code_tree.property("focused") is not True
    assert window.viewer.property("focused") is not True
    assert window.segment_list.property("focused") is not True


def test_focusing_the_code_tree_marks_only_the_code_tree(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()

    window.code_tree.setFocus()
    qtbot.waitUntil(lambda: window.code_tree.hasFocus())

    assert window.code_tree.property("focused") is True
    assert window.segment_list.property("focused") is not True
    assert window.viewer.property("focused") is not True


def test_focusing_the_segment_list_marks_only_the_segment_list(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()

    window.segment_list.setFocus()
    qtbot.waitUntil(lambda: window.segment_list.hasFocus())

    assert window.segment_list.property("focused") is True
    assert window.code_tree.property("focused") is not True
    assert window.viewer.property("focused") is not True


def test_switching_focus_clears_the_previous_pane(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()

    window.viewer.setFocus()
    qtbot.waitUntil(lambda: window.viewer.hasFocus())
    assert window.viewer.property("focused") is True

    window.document_list.setFocus()
    qtbot.waitUntil(lambda: window.document_list.hasFocus())

    assert window.document_list.property("focused") is True
    assert window.viewer.property("focused") is not True


def test_switching_from_code_tree_to_segment_list_deselects_the_code_tree(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()

    window.code_tree.setFocus()
    qtbot.waitUntil(lambda: window.code_tree.hasFocus())
    assert window.code_tree.property("focused") is True

    window.segment_list.setFocus()
    qtbot.waitUntil(lambda: window.segment_list.hasFocus())

    assert window.segment_list.property("focused") is True
    assert window.code_tree.property("focused") is not True


def test_focusing_the_code_sort_combo_does_not_mark_anything_focused(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()

    window.code_sort_combo.setFocus()
    qtbot.waitUntil(lambda: window.code_sort_combo.hasFocus())

    assert window.code_tree.property("focused") is not True
    assert window.segment_list.property("focused") is not True


def test_focusing_the_apply_code_button_does_not_mark_anything_focused(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()

    window.apply_code_button.setFocus()
    qtbot.waitUntil(lambda: window.apply_code_button.hasFocus())

    assert window.code_tree.property("focused") is not True
    assert window.segment_list.property("focused") is not True
