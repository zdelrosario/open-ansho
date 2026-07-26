from opencoder.ui.main_window import MainWindow


def test_focusing_a_pane_marks_only_that_pane(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()

    window.viewer.setFocus()
    qtbot.waitUntil(lambda: window.viewer.hasFocus())

    assert window.viewer.property("focused") is True
    assert window.document_list.property("focused") is not True
    assert window.codebook_pane.property("focused") is not True
    assert window.segments_pane.property("focused") is not True


def test_focusing_a_widget_inside_the_codebook_marks_the_codebook_pane(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()

    window.code_filter_input.setFocus()
    qtbot.waitUntil(lambda: window.code_filter_input.hasFocus())

    assert window.codebook_pane.property("focused") is True
    assert window.viewer.property("focused") is not True
    assert window.segments_pane.property("focused") is not True


def test_focusing_the_segment_list_marks_only_the_segments_pane(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()

    window.segment_list.setFocus()
    qtbot.waitUntil(lambda: window.segment_list.hasFocus())

    assert window.segments_pane.property("focused") is True
    assert window.codebook_pane.property("focused") is not True
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


def test_switching_from_codebook_to_segments_deselects_the_codebook_pane(qtbot):
    """Regression test: Codebook and Coded Segments used to share one
    container pane, so moving focus between them never changed which
    pane was marked focused."""
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()

    window.code_filter_input.setFocus()
    qtbot.waitUntil(lambda: window.code_filter_input.hasFocus())
    assert window.codebook_pane.property("focused") is True

    window.segment_list.setFocus()
    qtbot.waitUntil(lambda: window.segment_list.hasFocus())

    assert window.segments_pane.property("focused") is True
    assert window.codebook_pane.property("focused") is not True
