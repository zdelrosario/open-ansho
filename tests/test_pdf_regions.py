"""Coding the parts of a PDF page that aren't text."""

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtTest import QTest

from openansho import db, pdf_extract, reporting
from openansho.ui.pdf_viewer import REGION_FREEHAND, REGION_RECTANGLE, PdfViewer
from test_pdf_viewer import OFF_TEXT, open_pdf, text_point, viewport_point

MARKER = pdf_extract.REGION_MARKER

PAGES = [["First page."], ["Second page."]]

# Region outlines in page fractions: the four corners of a rectangle.
FIGURE = [(0.08, 0.30), (0.38, 0.30), (0.38, 0.45), (0.08, 0.45)]
LOWER_FIGURE = [(0.08, 0.60), (0.38, 0.60), (0.38, 0.75), (0.08, 0.75)]


def _pdf_window(qtbot, tmp_path, write_pdf, pages=PAGES):
    return open_pdf(qtbot, tmp_path, write_pdf, pages=pages)


def _segments(window):
    return db.list_segments_for_document(window.conn, window._current_document_id)


def _regions(window):
    return db.list_regions_for_document(window.conn, window._current_document_id)


def _place_cursor(window, position):
    cursor = window.active_viewer.textCursor()
    cursor.setPosition(position)
    window.active_viewer.setTextCursor(cursor)


# -- drawing regions ----------------------------------------------------------


def test_drawing_a_region_adds_one_marker_at_the_end_of_its_page(
    qtbot, tmp_path, write_pdf
):
    window = _pdf_window(qtbot, tmp_path, write_pdf)

    region = window.create_region(0, FIGURE)

    content = window.active_viewer.toPlainText()
    assert content == f"First page.\n{MARKER}\n\f\nSecond page.\n"
    assert content[region.text_offset] == MARKER
    assert region.page == 0
    assert region.outline() == FIGURE


def test_a_region_keeps_its_outline_and_its_bounding_box(qtbot, tmp_path, write_pdf):
    window = _pdf_window(qtbot, tmp_path, write_pdf)

    region = window.create_region(0, FIGURE)

    assert (region.x, region.y) == (0.08, 0.30)
    assert round(region.width, 6) == 0.30
    assert round(region.height, 6) == 0.15


def test_the_marker_is_saved_to_the_documents_content(qtbot, tmp_path, write_pdf):
    window = _pdf_window(qtbot, tmp_path, write_pdf)

    window.create_region(1, FIGURE)

    doc = db.get_document(window.conn, window._current_document_id)
    assert doc.content == window.active_viewer.toPlainText()
    assert doc.content == f"First page.\n\f\nSecond page.\n{MARKER}\n"


def test_a_drawn_region_is_selected_and_ready_to_code(qtbot, tmp_path, write_pdf):
    window = _pdf_window(qtbot, tmp_path, write_pdf)

    region = window.create_region(0, FIGURE)

    cursor = window.active_viewer.textCursor()
    assert cursor.selectionStart() == region.text_offset
    assert cursor.selectionEnd() == region.text_offset + 1
    assert window.active_viewer.mode == PdfViewer.VISUAL


def test_regions_on_a_page_are_ordered_down_the_page(qtbot, tmp_path, write_pdf):
    window = _pdf_window(qtbot, tmp_path, write_pdf)

    lower = window.create_region(0, LOWER_FIGURE)
    upper = window.create_region(0, FIGURE)

    upper = db.get_region(window.conn, upper.id)
    lower = db.get_region(window.conn, lower.id)
    assert upper.text_offset < lower.text_offset


def test_drawing_a_region_moves_later_segments_along_with_the_text(
    qtbot, tmp_path, write_pdf
):
    window = _pdf_window(qtbot, tmp_path, write_pdf)
    code = window.add_code("Later")
    content = window.active_viewer.toPlainText()
    start = content.index("Second page.")
    window.apply_segment(code.id, start, start + len("Second page."))

    window.create_region(0, FIGURE)  # inserts a marker earlier in the document

    segment = _segments(window)[0]
    new_content = window.active_viewer.toPlainText()
    assert segment.start_offset == start + len(pdf_extract.REGION_MARKER_LINE)
    assert new_content[segment.start_offset : segment.end_offset] == "Second page."


def test_every_regions_marker_survives_another_region_being_added(
    qtbot, tmp_path, write_pdf
):
    window = _pdf_window(qtbot, tmp_path, write_pdf)

    window.create_region(1, FIGURE)
    window.create_region(0, FIGURE)
    window.create_region(1, LOWER_FIGURE)

    content = window.active_viewer.toPlainText()
    assert len(_regions(window)) == 3
    for region in _regions(window):
        assert content[region.text_offset] == MARKER


# -- the two region tools -----------------------------------------------------


def test_the_rectangle_tool_is_the_default(qtbot, tmp_path, write_pdf):
    window = _pdf_window(qtbot, tmp_path, write_pdf)

    assert window.pdf_pane.region_mode == REGION_RECTANGLE
    assert window.pdf_pane.rectangle_button.isChecked()
    assert not window.pdf_pane.freehand_button.isChecked()


def test_the_freehand_button_switches_tools_and_back(qtbot, tmp_path, write_pdf):
    window = _pdf_window(qtbot, tmp_path, write_pdf)

    window.pdf_pane.freehand_button.click()

    assert window.pdf_pane.region_mode == REGION_FREEHAND
    assert window.pdf_viewer.region_mode == REGION_FREEHAND

    window.pdf_pane.rectangle_button.click()

    assert window.pdf_pane.region_mode == REGION_RECTANGLE


def test_the_fixtures_figure_really_is_off_the_text(qtbot, tmp_path, write_pdf):
    """Guards the two points the drawing tests below are built on."""
    window = _pdf_window(qtbot, tmp_path, write_pdf)
    text_map = window.pdf_viewer._text_map

    assert text_map.is_over_text(0, QPointF(*text_point(window.pdf_viewer)))
    assert not text_map.is_over_text(0, QPointF(*OFF_TEXT))


def test_dragging_off_the_text_draws_a_rectangle(qtbot, tmp_path, write_pdf):
    window = _pdf_window(qtbot, tmp_path, write_pdf)
    viewer = window.pdf_viewer
    start = viewport_point(viewer, 0, OFF_TEXT)
    end = viewport_point(viewer, 0, (OFF_TEXT[0] + 120, OFF_TEXT[1] + 90))

    QTest.mousePress(viewer.viewport(), Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(viewer.viewport(), end)
    QTest.mouseRelease(viewer.viewport(), Qt.LeftButton, Qt.NoModifier, end)

    regions = _regions(window)
    assert len(regions) == 1
    assert len(regions[0].outline()) == 4  # a rectangle's corners
    assert regions[0].page == 0


def test_dragging_freehand_off_the_text_draws_the_shape_drawn(
    qtbot, tmp_path, write_pdf
):
    window = _pdf_window(qtbot, tmp_path, write_pdf)
    viewer = window.pdf_viewer
    window.pdf_pane.freehand_button.click()
    path = [(200, 300), (250, 290), (290, 320), (270, 370), (210, 360)]
    points = [viewport_point(viewer, 0, point) for point in path]

    QTest.mousePress(viewer.viewport(), Qt.LeftButton, Qt.NoModifier, points[0])
    for point in points[1:]:
        QTest.mouseMove(viewer.viewport(), point)
    QTest.mouseRelease(viewer.viewport(), Qt.LeftButton, Qt.NoModifier, points[-1])

    regions = _regions(window)
    assert len(regions) == 1
    # Every point of the drag is kept, so the stored shape is the drawn one
    # rather than the box around it.
    assert len(regions[0].outline()) > 4


def test_dragging_across_text_selects_instead_of_drawing_a_region(
    qtbot, tmp_path, write_pdf
):
    window = _pdf_window(qtbot, tmp_path, write_pdf)
    viewer = window.pdf_viewer
    start = viewport_point(viewer, 0, text_point(viewer))
    end = viewport_point(viewer, 0, text_point(viewer, index=9))

    QTest.mousePress(viewer.viewport(), Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(viewer.viewport(), end)
    QTest.mouseRelease(viewer.viewport(), Qt.LeftButton, Qt.NoModifier, end)

    assert _regions(window) == []
    assert viewer.textCursor().hasSelection()


def test_a_freehand_drag_across_text_also_selects_rather_than_drawing(
    qtbot, tmp_path, write_pdf
):
    window = _pdf_window(qtbot, tmp_path, write_pdf)
    viewer = window.pdf_viewer
    window.pdf_pane.freehand_button.click()
    start = viewport_point(viewer, 0, text_point(viewer))
    end = viewport_point(viewer, 0, text_point(viewer, index=9))

    QTest.mousePress(viewer.viewport(), Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(viewer.viewport(), end)
    QTest.mouseRelease(viewer.viewport(), Qt.LeftButton, Qt.NoModifier, end)

    assert _regions(window) == []
    assert viewer.textCursor().hasSelection()


def test_a_speck_of_a_drag_leaves_no_region(qtbot, tmp_path, write_pdf):
    window = _pdf_window(qtbot, tmp_path, write_pdf)
    viewer = window.pdf_viewer
    start = viewport_point(viewer, 0, OFF_TEXT)
    end = start + QPoint(7, 6)  # past the click threshold, under the size floor

    QTest.mousePress(viewer.viewport(), Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(viewer.viewport(), end)
    QTest.mouseRelease(viewer.viewport(), Qt.LeftButton, Qt.NoModifier, end)

    assert _regions(window) == []


def test_clicking_a_region_selects_it_on_the_page(qtbot, tmp_path, write_pdf):
    window = _pdf_window(qtbot, tmp_path, write_pdf)
    viewer = window.pdf_viewer
    region = window.create_region(0, FIGURE)
    _place_cursor(window, 0)

    middle = viewport_point(viewer, 0, (0.23 * 612, 0.375 * 792))
    QTest.mouseClick(viewer.viewport(), Qt.LeftButton, Qt.NoModifier, middle)

    assert viewer.region_at(middle) == region.id
    assert viewer.textCursor().selectionStart() == region.text_offset


# -- coding regions -----------------------------------------------------------


def test_a_region_is_coded_by_the_ordinary_coding_shortcut(qtbot, tmp_path, write_pdf):
    window = _pdf_window(qtbot, tmp_path, write_pdf)
    code = window.add_code("Figure")

    region = window.create_region(0, FIGURE)
    qtbot.waitUntil(lambda: window.pdf_viewer.hasFocus())
    QTest.keyClick(window.pdf_viewer, Qt.Key_Return)

    segments = _segments(window)
    assert len(segments) == 1
    assert segments[0].code_id == code.id
    assert (segments[0].start_offset, segments[0].end_offset) == (
        region.text_offset,
        region.text_offset + 1,
    )


def test_a_region_takes_more_than_one_code(qtbot, tmp_path, write_pdf):
    window = _pdf_window(qtbot, tmp_path, write_pdf)
    first = window.add_code("Figure")
    second = window.add_code("Method")

    region = window.create_region(0, FIGURE)
    window.apply_segment(first.id, region.text_offset, region.text_offset + 1)
    window.apply_segment(second.id, region.text_offset, region.text_offset + 1)

    assert {segment.code_id for segment in _segments(window)} == {first.id, second.id}
    assert len(window.pdf_viewer.marks) == 1
    assert len(window.pdf_viewer.marks[0].colors) == 2


def test_x_on_a_region_marker_removes_its_codes_but_keeps_the_region(
    qtbot, tmp_path, write_pdf
):
    window = _pdf_window(qtbot, tmp_path, write_pdf)
    code = window.add_code("Figure")
    region = window.create_region(0, FIGURE)
    window.apply_segment(code.id, region.text_offset, region.text_offset + 1)

    window.pdf_viewer.exit_visual_mode()
    _place_cursor(window, region.text_offset)
    window.pdf_viewer.setFocus()
    qtbot.waitUntil(lambda: window.pdf_viewer.hasFocus())
    QTest.keyClick(window.pdf_viewer, Qt.Key_X)

    assert _segments(window) == []
    assert db.get_region(window.conn, region.id) is not None


# -- what the page shows ------------------------------------------------------


def test_an_uncoded_region_is_drawn_without_a_color(qtbot, tmp_path, write_pdf):
    window = _pdf_window(qtbot, tmp_path, write_pdf)

    region = window.create_region(0, FIGURE)

    marks = window.pdf_viewer.marks
    assert [mark.region_id for mark in marks] == [region.id]
    assert marks[0].colors == ()
    assert marks[0].selected
    assert marks[0].points == tuple(FIGURE)


def test_a_coded_region_is_drawn_in_its_codes_color(qtbot, tmp_path, write_pdf):
    window = _pdf_window(qtbot, tmp_path, write_pdf)
    code = window.add_code("Figure")
    region = window.create_region(0, FIGURE)

    window.apply_segment(code.id, region.text_offset, region.text_offset + 1)

    mark = window.pdf_viewer.marks[0]
    assert mark.colors[0].name() == code.color.lower()
    assert mark.colors[0].alpha() < 255  # translucent, so the page shows through


def test_regions_from_every_page_are_known_to_the_pane(qtbot, tmp_path, write_pdf):
    window = _pdf_window(qtbot, tmp_path, write_pdf)

    first = window.create_region(0, FIGURE)
    second = window.create_region(1, FIGURE)

    # Pages scroll continuously, so both are drawn; each knows its own page.
    marks = {mark.region_id: mark.page for mark in window.pdf_viewer.marks}
    assert marks == {first.id: 0, second.id: 1}


def test_a_coded_span_of_text_is_highlighted_on_the_page(qtbot, tmp_path, write_pdf):
    window = _pdf_window(qtbot, tmp_path, write_pdf, pages=[["First page."]])
    code = window.add_code("Opening")

    window.apply_segment(code.id, 0, 5)

    viewer = window.pdf_viewer
    rects = viewer._text_map.rects_for_range(0, 5)
    assert len(rects) == 1
    page, rect = rects[0]
    assert page == 0
    assert viewer.page_rect(0).contains(viewer.from_page_rect(page, rect).toRect())


# -- editing and deleting -----------------------------------------------------


def test_deleting_a_region_removes_its_marker_and_its_codes(qtbot, tmp_path, write_pdf):
    window = _pdf_window(qtbot, tmp_path, write_pdf)
    code = window.add_code("Figure")
    region = window.create_region(0, FIGURE)
    window.apply_segment(code.id, region.text_offset, region.text_offset + 1)

    window.delete_region(region.id)

    assert db.get_region(window.conn, region.id) is None
    assert _segments(window) == []
    assert window.active_viewer.toPlainText() == "First page.\n\f\nSecond page.\n"
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

    content = window.active_viewer.toPlainText()
    assert {region.id for region in _regions(window)} == {lower.id, later.id}
    for region in _regions(window):
        assert content[region.text_offset] == MARKER


def test_regions_survive_reopening_the_project(qtbot, tmp_path, write_pdf):
    window = _pdf_window(qtbot, tmp_path, write_pdf)
    code = window.add_code("Figure")
    region = window.create_region(0, LOWER_FIGURE)
    window.apply_segment(code.id, region.text_offset, region.text_offset + 1)

    window.open_project(tmp_path / "project.sqlite")
    window.document_list.setCurrentRow(0)

    reopened = _regions(window)
    assert len(reopened) == 1
    assert reopened[0].text_offset == region.text_offset
    assert reopened[0].outline() == LOWER_FIGURE
    assert window.active_viewer.toPlainText()[reopened[0].text_offset] == MARKER
    assert window.pdf_viewer.marks[0].colors  # still coded, still colored


def test_a_region_stored_before_freehand_falls_back_to_its_box(tmp_path):
    """`points` is added by migration, so an older region has none."""
    conn = db.connect(tmp_path / "old.sqlite")
    doc = db.create_document(conn, "a.pdf", "x", kind=db.DOCUMENT_KIND_PDF)
    conn.execute(
        "INSERT INTO regions (document_id, page, text_offset, x, y, width, height, "
        "created_at) VALUES (?, 0, 0, 0.1, 0.2, 0.3, 0.4, 'now')",
        (doc.id,),
    )
    conn.commit()

    region = db.list_regions_for_document(conn, doc.id)[0]

    assert region.points is None
    assert region.outline() == [
        (0.1, 0.2),
        (0.4, 0.2),
        (0.4, 0.6000000000000001),
        (0.1, 0.6000000000000001),
    ]


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

    exported = path.read_text(encoding="utf-8")
    assert "[image region, page 2]" in exported
    assert MARKER not in exported


def test_the_coded_segments_pane_describes_a_region(qtbot, tmp_path, write_pdf):
    window = _pdf_window(qtbot, tmp_path, write_pdf)
    code = window.add_code("Figure")
    region = window.create_region(0, FIGURE)
    window.apply_segment(code.id, region.text_offset, region.text_offset + 1)

    labels = [
        window.segment_list.item(row).text() for row in range(window.segment_list.count())
    ]
    assert any("[image region, page 1]" in label for label in labels)
