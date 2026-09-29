from PySide6.QtCore import QPoint, QRect, QRectF, Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtTest import QTest

from openansho import db, pdf_extract, reporting
from openansho.ui.main_window import MainWindow
from openansho.ui.vim_viewer import VimTextViewer

MARKER = pdf_extract.REGION_MARKER

# Somewhere over the figure each sample page carries, in page fractions.
FIGURE = QRectF(0.08, 0.20, 0.30, 0.15)
LOWER_FIGURE = QRectF(0.08, 0.60, 0.30, 0.15)


def _pdf_window(qtbot, tmp_path, write_pdf, pages=(["First page."], ["Second page."])):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    window.create_project(tmp_path / "project.sqlite")
    write_pdf(tmp_path / "doc.pdf", list(pages))
    window.import_document(tmp_path / "doc.pdf")
    window.document_list.setCurrentRow(0)
    return window


def _segments(window):
    return db.list_segments_for_document(window.conn, window._current_document_id)


def _place_cursor(window, position):
    cursor = window.viewer.textCursor()
    cursor.setPosition(position)
    window.viewer.setTextCursor(cursor)


# -- drawing regions ----------------------------------------------------------


def test_drawing_a_region_adds_one_marker_at_the_end_of_its_page(qtbot, tmp_path, write_pdf):
    window = _pdf_window(qtbot, tmp_path, write_pdf)

    region = window.create_region(0, FIGURE)

    content = window.viewer.toPlainText()
    assert content == f"First page.\n{MARKER}\n\f\nSecond page.\n"
    assert content[region.text_offset] == MARKER
    assert region.page == 0
    assert (region.x, region.y, region.width, region.height) == (
        FIGURE.x(),
        FIGURE.y(),
        FIGURE.width(),
        FIGURE.height(),
    )


def test_the_marker_is_saved_to_the_documents_content(qtbot, tmp_path, write_pdf):
    window = _pdf_window(qtbot, tmp_path, write_pdf)

    window.create_region(1, FIGURE)

    doc = db.get_document(window.conn, window._current_document_id)
    assert doc.content == window.viewer.toPlainText()
    assert doc.content == f"First page.\n\f\nSecond page.\n{MARKER}\n"


def test_a_drawn_region_is_selected_and_ready_to_code(qtbot, tmp_path, write_pdf):
    window = _pdf_window(qtbot, tmp_path, write_pdf)

    region = window.create_region(0, FIGURE)

    cursor = window.viewer.textCursor()
    assert cursor.selectionStart() == region.text_offset
    assert cursor.selectionEnd() == region.text_offset + 1
    assert window.viewer.mode == VimTextViewer.VISUAL
    assert window.pdf_view.page == 0


def test_regions_on_a_page_are_ordered_down_the_page(qtbot, tmp_path, write_pdf):
    window = _pdf_window(qtbot, tmp_path, write_pdf)

    lower = window.create_region(0, LOWER_FIGURE)
    upper = window.create_region(0, FIGURE)

    upper = db.get_region(window.conn, upper.id)
    lower = db.get_region(window.conn, lower.id)
    assert upper.text_offset < lower.text_offset
    assert window.viewer.toPlainText().startswith(f"First page.\n{MARKER}\n{MARKER}\n\f")


def test_drawing_a_region_moves_later_segments_along_with_the_text(
    qtbot, tmp_path, write_pdf
):
    window = _pdf_window(qtbot, tmp_path, write_pdf)
    code = window.add_code("Later")
    content = window.viewer.toPlainText()
    start = content.index("Second page.")
    window.apply_segment(code.id, start, start + len("Second page."))

    window.create_region(0, FIGURE)  # inserts a marker earlier in the document

    segment = _segments(window)[0]
    new_content = window.viewer.toPlainText()
    assert segment.start_offset == start + len(pdf_extract.REGION_MARKER_LINE)
    assert new_content[segment.start_offset : segment.end_offset] == "Second page."


def test_a_region_only_shifts_markers_after_it(qtbot, tmp_path, write_pdf):
    window = _pdf_window(qtbot, tmp_path, write_pdf)

    second_page_region = window.create_region(1, FIGURE)
    first_page_region = window.create_region(0, FIGURE)

    content = window.viewer.toPlainText()
    for region in db.list_regions_for_document(window.conn, window._current_document_id):
        assert content[region.text_offset] == MARKER
    assert db.get_region(window.conn, first_page_region.id).page == 0
    assert db.get_region(
        window.conn, second_page_region.id
    ).text_offset > first_page_region.text_offset


# -- coding regions -----------------------------------------------------------


def test_a_region_is_coded_by_the_ordinary_coding_shortcut(qtbot, tmp_path, write_pdf):
    window = _pdf_window(qtbot, tmp_path, write_pdf)
    code = window.add_code("Figure")

    region = window.create_region(0, FIGURE)
    qtbot.waitUntil(lambda: window.viewer.hasFocus())
    QTest.keyClick(window.viewer, Qt.Key_Return)

    segments = _segments(window)
    assert len(segments) == 1
    assert segments[0].code_id == code.id
    assert segments[0].start_offset == region.text_offset
    assert segments[0].end_offset == region.text_offset + 1


def test_a_region_takes_more_than_one_code(qtbot, tmp_path, write_pdf):
    window = _pdf_window(qtbot, tmp_path, write_pdf)
    first = window.add_code("Figure")
    second = window.add_code("Method")

    region = window.create_region(0, FIGURE)
    window.apply_segment(first.id, region.text_offset, region.text_offset + 1)
    window.apply_segment(second.id, region.text_offset, region.text_offset + 1)

    assert {segment.code_id for segment in _segments(window)} == {first.id, second.id}
    assert len(window.pdf_view.marks) == 1
    assert len(window.pdf_view.marks[0].colors) == 2


def test_clicking_a_region_selects_it_for_coding(qtbot, tmp_path, write_pdf):
    window = _pdf_window(qtbot, tmp_path, write_pdf)
    region = window.create_region(0, FIGURE)
    _place_cursor(window, 0)

    window.select_region(region.id)

    cursor = window.viewer.textCursor()
    assert (cursor.selectionStart(), cursor.selectionEnd()) == (
        region.text_offset,
        region.text_offset + 1,
    )


def test_x_on_a_region_marker_removes_its_codes_but_keeps_the_region(
    qtbot, tmp_path, write_pdf
):
    window = _pdf_window(qtbot, tmp_path, write_pdf)
    code = window.add_code("Figure")
    region = window.create_region(0, FIGURE)
    window.apply_segment(code.id, region.text_offset, region.text_offset + 1)

    window.viewer.exit_visual_mode()
    _place_cursor(window, region.text_offset)
    window.viewer.setFocus()
    qtbot.waitUntil(lambda: window.viewer.hasFocus())
    QTest.keyClick(window.viewer, Qt.Key_X)

    assert _segments(window) == []
    assert db.get_region(window.conn, region.id) is not None


# -- the page pane ------------------------------------------------------------


def test_an_uncoded_region_is_drawn_without_a_color(qtbot, tmp_path, write_pdf):
    window = _pdf_window(qtbot, tmp_path, write_pdf)

    region = window.create_region(0, FIGURE)

    marks = window.pdf_view.marks
    assert [mark.region_id for mark in marks] == [region.id]
    assert marks[0].colors == ()
    assert marks[0].selected


def test_a_coded_region_is_drawn_in_its_codes_color(qtbot, tmp_path, write_pdf):
    window = _pdf_window(qtbot, tmp_path, write_pdf)
    code = window.add_code("Figure")
    region = window.create_region(0, FIGURE)

    window.apply_segment(code.id, region.text_offset, region.text_offset + 1)

    mark = window.pdf_view.marks[0]
    assert mark.colors[0].name() == code.color.lower()
    assert mark.colors[0].alpha() < 255  # translucent, so the page shows through


def test_only_the_visible_pages_regions_are_drawn(qtbot, tmp_path, write_pdf):
    window = _pdf_window(qtbot, tmp_path, write_pdf)
    first = window.create_region(0, FIGURE)
    second = window.create_region(1, FIGURE)

    window.pdf_view.set_page(0)
    window._refresh_region_marks()
    assert [mark.region_id for mark in window.pdf_view.marks] == [first.id]

    window.pdf_view.set_page(1)
    window._refresh_region_marks()
    assert [mark.region_id for mark in window.pdf_view.marks] == [second.id]


def test_a_regions_rectangle_maps_onto_the_rendered_page(qtbot, tmp_path, write_pdf):
    window = _pdf_window(qtbot, tmp_path, write_pdf)
    canvas = window.pdf_view.canvas
    canvas.resize(300, 400)
    window.create_region(0, FIGURE)

    page_rect = canvas.page_rect()
    drawn = canvas.from_page_fractions(FIGURE)

    assert page_rect.contains(drawn)
    assert canvas.region_at(drawn.center()) == window.pdf_view.marks[0].region_id
    assert canvas.region_at(page_rect.bottomRight()) is None


def test_dragging_on_the_page_creates_a_region_there(qtbot, tmp_path, write_pdf):
    window = _pdf_window(qtbot, tmp_path, write_pdf)
    canvas = window.pdf_view.canvas
    canvas.resize(300, 400)
    page_rect = canvas.page_rect()
    start = page_rect.topLeft() + QPoint(20, 30)
    end = start + QPoint(90, 60)

    QTest.mousePress(canvas, Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(canvas, end)
    QTest.mouseRelease(canvas, Qt.LeftButton, Qt.NoModifier, end)

    regions = db.list_regions_for_document(window.conn, window._current_document_id)
    assert len(regions) == 1
    assert regions[0].page == 0
    assert canvas.from_page_fractions(
        QRectF(regions[0].x, regions[0].y, regions[0].width, regions[0].height)
    ) == QRect(start, end).normalized()
    assert window.viewer.textCursor().selectionStart() == regions[0].text_offset


def test_a_bare_click_on_empty_page_space_creates_nothing(qtbot, tmp_path, write_pdf):
    window = _pdf_window(qtbot, tmp_path, write_pdf)
    canvas = window.pdf_view.canvas
    canvas.resize(300, 400)
    point = canvas.page_rect().center()

    QTest.mouseClick(canvas, Qt.LeftButton, Qt.NoModifier, point)

    assert db.list_regions_for_document(window.conn, window._current_document_id) == []


def test_clicking_a_region_on_the_page_selects_its_marker(qtbot, tmp_path, write_pdf):
    window = _pdf_window(qtbot, tmp_path, write_pdf)
    canvas = window.pdf_view.canvas
    canvas.resize(300, 400)
    region = window.create_region(0, FIGURE)
    _place_cursor(window, 0)

    QTest.mouseClick(
        canvas,
        Qt.LeftButton,
        Qt.NoModifier,
        canvas.from_page_fractions(FIGURE).center(),
    )

    assert window.viewer.textCursor().selectionStart() == region.text_offset
    assert window.viewer.mode == VimTextViewer.VISUAL


def test_a_rectangle_dragged_on_the_canvas_becomes_page_fractions(
    qtbot, tmp_path, write_pdf
):
    window = _pdf_window(qtbot, tmp_path, write_pdf)
    canvas = window.pdf_view.canvas
    canvas.resize(300, 400)
    page_rect = canvas.page_rect()

    half = page_rect.adjusted(0, 0, -page_rect.width() // 2, -page_rect.height() // 2)
    fractions = canvas.to_page_fractions(half)

    assert 0.45 < fractions.width() < 0.55
    assert 0.45 < fractions.height() < 0.55
    assert fractions.x() < 0.01


# -- vim navigation over a region ---------------------------------------------


def test_a_region_marker_is_a_single_character_for_the_vim_motions(
    qtbot, tmp_path, write_pdf
):
    window = _pdf_window(qtbot, tmp_path, write_pdf)
    region = window.create_region(0, FIGURE)
    window.viewer.exit_visual_mode()
    qtbot.waitUntil(lambda: window.viewer.hasFocus())

    # The marker sits alone on its own line, so k/j step onto and off it...
    _place_cursor(window, region.text_offset)
    QTest.keyClick(window.viewer, Qt.Key_K)
    assert window.viewer.textCursor().position() == 0  # the line of text above

    QTest.keyClick(window.viewer, Qt.Key_J)
    assert window.viewer.textCursor().position() == region.text_offset

    # ...and one l moves clear of it, rather than through an image's worth of text.
    QTest.keyClick(window.viewer, Qt.Key_L)
    assert window.viewer.textCursor().position() == region.text_offset + 1


def test_a_region_marker_is_one_step_for_the_word_motions(qtbot, tmp_path, write_pdf):
    window = _pdf_window(qtbot, tmp_path, write_pdf, pages=[["Figure follows."]])
    region = window.create_region(0, FIGURE)
    window.viewer.exit_visual_mode()
    _place_cursor(window, 0)
    qtbot.waitUntil(lambda: window.viewer.hasFocus())

    QTest.keyClick(window.viewer, Qt.Key_W, Qt.ShiftModifier)  # onto "follows."
    QTest.keyClick(window.viewer, Qt.Key_W, Qt.ShiftModifier)  # onto the marker

    assert window.viewer.textCursor().position() == region.text_offset


def test_a_pdf_with_no_text_at_all_can_still_be_coded_by_region(
    qtbot, tmp_path, write_pdf
):
    """A scanned document extracts to nothing, so its regions are the only
    thing there is to code."""
    window = _pdf_window(qtbot, tmp_path, write_pdf, pages=[[], []])
    code = window.add_code("Scan")

    # Nothing but the page separator: two pages, no text on either.
    assert window.viewer.toPlainText() == "\n\f\n\n"

    region = window.create_region(1, FIGURE)
    window.apply_segment(code.id, region.text_offset, region.text_offset + 1)

    assert window.viewer.toPlainText() == f"\n\f\n\n{MARKER}\n"
    assert window.viewer.toPlainText()[region.text_offset] == MARKER
    assert [segment.code_id for segment in _segments(window)] == [code.id]


# -- editing and deleting -----------------------------------------------------


def test_deleting_a_region_removes_its_marker_and_its_codes(qtbot, tmp_path, write_pdf):
    window = _pdf_window(qtbot, tmp_path, write_pdf)
    code = window.add_code("Figure")
    region = window.create_region(0, FIGURE)
    window.apply_segment(code.id, region.text_offset, region.text_offset + 1)

    window.delete_region(region.id)

    assert db.get_region(window.conn, region.id) is None
    assert _segments(window) == []
    assert MARKER not in window.viewer.toPlainText()
    assert window.viewer.toPlainText() == "First page.\n\f\nSecond page.\n"
    assert db.get_document(window.conn, window._current_document_id).content == (
        "First page.\n\f\nSecond page.\n"
    )


def test_deleting_a_region_keeps_the_other_regions_pointing_at_their_markers(
    qtbot, tmp_path, write_pdf
):
    window = _pdf_window(qtbot, tmp_path, write_pdf)
    upper = window.create_region(0, FIGURE)
    lower = window.create_region(0, LOWER_FIGURE)
    later = window.create_region(1, FIGURE)

    window.delete_region(upper.id)

    content = window.viewer.toPlainText()
    remaining = db.list_regions_for_document(window.conn, window._current_document_id)
    assert {region.id for region in remaining} == {lower.id, later.id}
    for region in remaining:
        assert content[region.text_offset] == MARKER


def test_editing_the_marker_away_deletes_the_region(qtbot, tmp_path, write_pdf):
    window = _pdf_window(qtbot, tmp_path, write_pdf)
    region = window.create_region(0, FIGURE)
    window.viewer.exit_visual_mode()

    window.viewer.enter_insert_mode()
    cursor = window.viewer.textCursor()
    cursor.setPosition(region.text_offset)
    cursor.setPosition(region.text_offset + 1, QTextCursor.KeepAnchor)
    window.viewer.setTextCursor(cursor)
    QTest.keyClick(window.viewer, Qt.Key_Backspace)

    assert db.get_region(window.conn, region.id) is None
    assert MARKER not in window.viewer.toPlainText()


def test_typing_before_a_marker_moves_the_region_with_it(qtbot, tmp_path, write_pdf):
    window = _pdf_window(qtbot, tmp_path, write_pdf)
    region = window.create_region(0, FIGURE)
    window.viewer.exit_visual_mode()

    window.viewer.enter_insert_mode()
    _place_cursor(window, 0)
    QTest.keyClicks(window.viewer, "Hi ")

    moved = db.get_region(window.conn, region.id)
    assert moved is not None
    assert moved.text_offset == region.text_offset + 3
    assert window.viewer.toPlainText()[moved.text_offset] == MARKER


def test_regions_survive_reopening_the_project(qtbot, tmp_path, write_pdf):
    window = _pdf_window(qtbot, tmp_path, write_pdf)
    code = window.add_code("Figure")
    region = window.create_region(0, FIGURE)
    window.apply_segment(code.id, region.text_offset, region.text_offset + 1)

    window.open_project(tmp_path / "project.sqlite")
    window.document_list.setCurrentRow(0)

    reopened = db.list_regions_for_document(window.conn, window._current_document_id)
    assert len(reopened) == 1
    assert reopened[0].text_offset == region.text_offset
    assert window.viewer.toPlainText()[reopened[0].text_offset] == MARKER
    assert [mark.colors for mark in window.pdf_view.marks] != [()]


# -- reporting ----------------------------------------------------------------


def test_exports_describe_a_coded_region_instead_of_its_marker(
    qtbot, tmp_path, write_pdf
):
    window = _pdf_window(qtbot, tmp_path, write_pdf)
    code = window.add_code("Figure")
    region = window.create_region(1, FIGURE)
    window.apply_segment(code.id, region.text_offset, region.text_offset + 1)

    path = tmp_path / "segments.csv"
    reporting.export_segments_csv(window.conn, path)

    assert "[image region, page 2]" in path.read_text(encoding="utf-8")
    assert MARKER not in path.read_text(encoding="utf-8")


def test_the_coded_segments_pane_describes_a_region(qtbot, tmp_path, write_pdf):
    window = _pdf_window(qtbot, tmp_path, write_pdf)
    code = window.add_code("Figure")
    region = window.create_region(0, FIGURE)
    window.apply_segment(code.id, region.text_offset, region.text_offset + 1)

    labels = [
        window.segment_list.item(row).text() for row in range(window.segment_list.count())
    ]
    assert any("[image region, page 1]" in label for label in labels)


def test_a_segment_spanning_text_and_a_region_keeps_both(qtbot, tmp_path, write_pdf):
    window = _pdf_window(qtbot, tmp_path, write_pdf, pages=[["Caption."]])
    code = window.add_code("Figure")
    region = window.create_region(0, FIGURE)
    window.apply_segment(code.id, 0, region.text_offset + 1)

    document = db.get_document(window.conn, window._current_document_id)
    regions_by_offset = {region.text_offset: region}
    text = reporting.segment_text(document, _segments(window)[0], regions_by_offset)

    assert text == "Caption.\n[image region, page 1]"
