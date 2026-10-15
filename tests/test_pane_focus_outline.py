from openansho.ui.main_window import PANE_FOCUS_STYLE, MainWindow


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


def test_every_pane_marked_focused_has_a_focus_outline_rule(qtbot):
    # Setting the property does nothing visible unless the stylesheet has a
    # `[focused="true"]` rule naming the pane — the PDF pane once had the
    # property toggled but no rule, so it never lit up.
    window = MainWindow()
    qtbot.addWidget(window)

    for pane in window._panes:
        assert pane.objectName()
        assert f'#{pane.objectName()}[focused="true"]' in PANE_FOCUS_STYLE


def test_focusing_the_pdf_pane_marks_only_the_pdf_pane(qtbot, tmp_path, write_pdf):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    window.create_project(tmp_path / "project.sqlite")
    write_pdf(tmp_path / "doc.pdf", [["Only line."]])
    window.import_document(tmp_path / "doc.pdf")
    window.document_list.setCurrentRow(0)

    window.pdf_viewer.setFocus()
    qtbot.waitUntil(lambda: window.pdf_viewer.hasFocus())

    assert window.pdf_viewer.property("focused") is True
    assert window.document_list.property("focused") is not True
    assert window.code_tree.property("focused") is not True


def test_focusing_the_apply_code_button_does_not_mark_anything_focused(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()

    window.apply_code_button.setFocus()
    qtbot.waitUntil(lambda: window.apply_code_button.hasFocus())

    assert window.code_tree.property("focused") is not True
    assert window.segment_list.property("focused") is not True
