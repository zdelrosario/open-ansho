"""The PDF pane itself: how it lays pages out, zooms, and carries a cursor."""

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from openansho.ui.main_window import MainWindow
from openansho.ui.pdf_viewer import PdfPane, PdfViewer
from openansho.ui.vim_viewer import VimTextViewer

PAGES = [
    ["First page first line.", "First page second line."],
    ["Second page only line."],
]

# Somewhere inside the figure the fixture draws, in page coordinates (PDF
# points from the top-left): well below two lines of text, and the nearest
# thing the fixture has to a non-text area. Points *on* text are asked for
# rather than assumed — see `text_point` — since exactly where a glyph lands
# is the PDF renderer's business, not something a test should hardcode.
OFF_TEXT = (200, 300)


def text_point(viewer, page=0, index=0):
    """Page coordinates of the middle of the `index`-th glyph on `page`.

    Counts only characters that have a glyph: spaces and line breaks have
    none, so there is no point on the page that means "the space".
    """
    text_map = viewer._text_map
    start, end = text_map.page_range(page)
    seen = 0
    for offset in range(start, end):
        located = text_map.rect_for_offset(offset)
        if located is None:
            continue
        if seen == index:
            return located[1].center().x(), located[1].center().y()
        seen += 1
    raise AssertionError(f"page {page} has fewer than {index + 1} glyphs")


def open_pdf(qtbot, tmp_path, write_pdf, pages=PAGES, viewport=(700, 400)):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    window.create_project(tmp_path / "project.sqlite")
    write_pdf(tmp_path / "doc.pdf", list(pages))
    window.import_document(tmp_path / "doc.pdf")
    window.document_list.setCurrentRow(0)
    window.pdf_viewer.viewport().resize(*viewport)
    window.pdf_viewer.resize(viewport[0] + 20, viewport[1] + 20)
    return window


def viewport_point(viewer, page, page_point):
    """A point in page coordinates, as a point in the viewport."""
    rect = viewer.page_rect(page)
    x, y = page_point
    return QPoint(int(rect.x() + x * viewer.zoom), int(rect.y() + y * viewer.zoom))


# -- one pane -----------------------------------------------------------------


def test_a_pdf_replaces_the_text_pane_rather_than_sitting_beside_it(
    qtbot, tmp_path, write_pdf
):
    window = open_pdf(qtbot, tmp_path, write_pdf)

    assert window.viewer_stack.currentWidget() is window.pdf_pane
    assert isinstance(window.active_viewer, PdfViewer)
    assert not window.viewer.isVisible()


def test_a_text_document_still_gets_the_text_pane(qtbot, tmp_path, write_pdf):
    window = open_pdf(qtbot, tmp_path, write_pdf)
    path = tmp_path / "notes.txt"
    path.write_text("Plain text.", encoding="utf-8")
    window.import_document(path)

    assert window.viewer_stack.currentWidget() is window.viewer
    assert isinstance(window.active_viewer, VimTextViewer)
    assert window.active_viewer.toPlainText() == "Plain text."


def test_switching_away_from_a_pdf_leaves_no_text_behind_in_its_pane(
    qtbot, tmp_path, write_pdf
):
    window = open_pdf(qtbot, tmp_path, write_pdf)
    path = tmp_path / "notes.txt"
    path.write_text("Plain text.", encoding="utf-8")
    window.import_document(path)

    assert window.pdf_viewer.toPlainText() == ""


def test_the_pane_holds_the_documents_text(qtbot, tmp_path, write_pdf):
    window = open_pdf(qtbot, tmp_path, write_pdf)

    assert window.active_viewer.toPlainText().startswith("First page first line.")
    assert "Second page only line." in window.active_viewer.toPlainText()


# -- continuous scrolling -----------------------------------------------------


def test_pages_are_stacked_one_below_the_next(qtbot, tmp_path, write_pdf):
    window = open_pdf(qtbot, tmp_path, write_pdf)
    viewer = window.pdf_viewer

    first, second = viewer.page_rect(0), viewer.page_rect(1)
    assert viewer.page_count == 2
    assert second.top() > first.bottom()
    assert first.width() == second.width()


def test_the_whole_document_is_one_scroll_range(qtbot, tmp_path, write_pdf):
    window = open_pdf(qtbot, tmp_path, write_pdf)
    viewer = window.pdf_viewer

    # Both pages plus the gap, not one page at a time.
    assert viewer.verticalScrollBar().maximum() > viewer.page_rect(0).height()

    viewer.verticalScrollBar().setValue(viewer.verticalScrollBar().maximum())

    assert viewer.page_rect(1).bottom() <= viewer.viewport().height() + 1
    assert viewer.page_rect(0).top() < 0  # page one has scrolled off the top


# -- zoom ---------------------------------------------------------------------


def test_zooming_in_makes_the_pages_bigger(qtbot, tmp_path, write_pdf):
    window = open_pdf(qtbot, tmp_path, write_pdf)
    viewer = window.pdf_viewer
    before = viewer.page_rect(0)

    viewer.set_zoom(2.0)

    assert viewer.zoom == 2.0
    assert viewer.page_rect(0).width() == before.width() * 2
    assert viewer.page_rect(0).height() == before.height() * 2


def test_a_page_wider_than_the_pane_can_be_scrolled_sideways(
    qtbot, tmp_path, write_pdf
):
    window = open_pdf(qtbot, tmp_path, write_pdf, viewport=(300, 400))
    viewer = window.pdf_viewer
    assert viewer.horizontalScrollBar().maximum() > 0  # the page starts wider

    viewer.set_zoom(3.0)
    wide = viewer.horizontalScrollBar().maximum()
    viewer.horizontalScrollBar().setValue(wide)

    assert wide > 0
    assert viewer.page_rect(0).left() < 0  # scrolled past the page's left edge


def test_zoom_is_clamped_to_a_usable_range(qtbot, tmp_path, write_pdf):
    viewer = open_pdf(qtbot, tmp_path, write_pdf).pdf_viewer

    viewer.set_zoom(1000.0)
    assert viewer.zoom <= 6.0

    viewer.set_zoom(0.0001)
    assert viewer.zoom >= 0.25


def test_the_zoom_buttons_and_label_track_the_zoom(qtbot, tmp_path, write_pdf):
    window = open_pdf(qtbot, tmp_path, write_pdf)
    pane = window.pdf_pane

    pane.zoom_in_button.click()
    assert pane.viewer.zoom > 1.0
    assert pane.zoom_label.text() == f"{round(pane.viewer.zoom * 100)}%"

    pane.zoom_out_button.click()
    assert pane.viewer.zoom == 1.0


def test_ctrl_scroll_zooms(qtbot, tmp_path, write_pdf):
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QWheelEvent

    viewer = open_pdf(qtbot, tmp_path, write_pdf).pdf_viewer
    point = QPointF(viewer.viewport().rect().center())
    event = QWheelEvent(
        point,
        viewer.viewport().mapToGlobal(point),
        QPoint(0, 0),
        QPoint(0, 120),
        Qt.NoButton,
        Qt.ControlModifier,
        Qt.NoScrollPhase,
        False,
    )

    viewer.wheelEvent(event)

    assert viewer.zoom > 1.0


# -- the text cursor on the page ----------------------------------------------


def test_the_cursor_sits_on_the_character_it_is_at(qtbot, tmp_path, write_pdf):
    window = open_pdf(qtbot, tmp_path, write_pdf)
    viewer = window.pdf_viewer

    rect = viewer._cursor_rect(0)

    assert viewer.page_rect(0).contains(rect.toRect())
    assert rect.width() > 0 and rect.height() > 0


def test_vim_motions_move_the_cursor_through_the_pdfs_text(qtbot, tmp_path, write_pdf):
    window = open_pdf(qtbot, tmp_path, write_pdf)
    viewer = window.pdf_viewer
    viewer.setFocus()
    qtbot.waitUntil(lambda: viewer.hasFocus())

    QTest.keyClick(viewer, Qt.Key_L)
    assert viewer.textCursor().position() == 1

    QTest.keyClick(viewer, Qt.Key_W)
    assert viewer.toPlainText()[viewer.textCursor().position() :].startswith("page")

    QTest.keyClick(viewer, Qt.Key_J)
    assert viewer.textCursor().blockNumber() == 1

    QTest.keyClick(viewer, Qt.Key_G, Qt.ShiftModifier)
    assert viewer.textCursor().position() == len(viewer.toPlainText())


def test_visual_mode_selects_text_on_the_page(qtbot, tmp_path, write_pdf):
    window = open_pdf(qtbot, tmp_path, write_pdf)
    viewer = window.pdf_viewer
    viewer.setFocus()
    qtbot.waitUntil(lambda: viewer.hasFocus())

    QTest.keyClick(viewer, Qt.Key_V)
    for _ in range(5):
        QTest.keyClick(viewer, Qt.Key_L)

    assert viewer.mode == PdfViewer.VISUAL
    cursor = viewer.textCursor()
    assert cursor.selectedText() == "First"


def test_search_works_in_the_pdf_pane(qtbot, tmp_path, write_pdf):
    window = open_pdf(qtbot, tmp_path, write_pdf)
    viewer = window.pdf_viewer
    viewer.setFocus()
    qtbot.waitUntil(lambda: viewer.hasFocus())

    QTest.keyClick(viewer, Qt.Key_Slash)
    QTest.keyClicks(viewer, "second")
    QTest.keyClick(viewer, Qt.Key_Return)

    position = viewer.textCursor().position()
    assert viewer.toPlainText()[position:].startswith("second line.")


def test_the_cursor_scrolls_into_view_when_it_moves_off_screen(
    qtbot, tmp_path, write_pdf
):
    window = open_pdf(qtbot, tmp_path, write_pdf)
    viewer = window.pdf_viewer
    assert viewer.verticalScrollBar().value() == 0

    cursor = viewer.textCursor()
    cursor.setPosition(viewer.toPlainText().index("Second page only line."))
    viewer.setTextCursor(cursor)

    assert viewer.verticalScrollBar().value() > 0
    assert 0 <= viewer._cursor_rect().top() <= viewer.viewport().height()


# -- no insert mode -----------------------------------------------------------


def test_a_pdf_has_no_insert_mode(qtbot, tmp_path, write_pdf):
    window = open_pdf(qtbot, tmp_path, write_pdf)
    viewer = window.pdf_viewer
    viewer.setFocus()
    qtbot.waitUntil(lambda: viewer.hasFocus())
    before = viewer.toPlainText()

    QTest.keyClick(viewer, Qt.Key_I)
    QTest.keyClicks(viewer, "typed")

    assert viewer.mode == PdfViewer.NORMAL
    assert viewer.toPlainText() == before
    assert not PdfViewer.supports_insert_mode


def test_calling_enter_insert_mode_on_a_pdf_does_nothing(qtbot, tmp_path, write_pdf):
    viewer = open_pdf(qtbot, tmp_path, write_pdf).pdf_viewer

    viewer.enter_insert_mode()

    assert viewer.mode == PdfViewer.NORMAL


def test_the_insert_mode_button_is_disabled_for_a_pdf(qtbot, tmp_path, write_pdf):
    window = open_pdf(qtbot, tmp_path, write_pdf)
    assert not window.insert_mode_button.isEnabled()

    path = tmp_path / "notes.txt"
    path.write_text("Plain text.", encoding="utf-8")
    window.import_document(path)

    assert window.insert_mode_button.isEnabled()


# -- mouse on the text --------------------------------------------------------


def test_clicking_a_word_puts_the_cursor_there(qtbot, tmp_path, write_pdf):
    window = open_pdf(qtbot, tmp_path, write_pdf)
    viewer = window.pdf_viewer

    QTest.mouseClick(
        viewer.viewport(), Qt.LeftButton, Qt.NoModifier, viewport_point(viewer, 0, text_point(viewer))
    )

    position = viewer.textCursor().position()
    assert viewer.toPlainText()[position] in "First "
    assert position < len("First page first line.")


def test_clicking_in_a_text_block_covers_one_character_not_a_swathe_of_page(
    qtbot, tmp_path, write_pdf
):
    """Regression: see `test_a_character_is_only_ever_as_tall_as_its_own_line`.

    The user-facing half of it — the cursor is what makes an over-tall
    character box visible, as a block covering far more than it should.
    """
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    window.create_project(tmp_path / "project.sqlite")
    write_pdf(
        tmp_path / "journal.pdf",
        [["Body line one.", "Body line two."]],
        strays=[[(50, 47, "footer line here"), (300, 577, "5")]],
    )
    window.import_document(tmp_path / "journal.pdf")
    window.document_list.setCurrentRow(0)
    viewer = window.pdf_viewer
    viewer.viewport().resize(700, 900)

    footer = viewer.toPlainText().index("footer line here")
    _page, glyph = viewer._text_map.rect_for_offset(footer)
    QTest.mouseClick(
        viewer.viewport(),
        Qt.LeftButton,
        Qt.NoModifier,
        viewport_point(viewer, 0, (glyph.center().x(), glyph.center().y())),
    )

    rect = viewer._cursor_rect()
    assert viewer.textCursor().position() == footer
    assert rect.height() < 0.05 * viewer.page_rect(0).height()


def test_dragging_across_words_selects_them(qtbot, tmp_path, write_pdf):
    window = open_pdf(qtbot, tmp_path, write_pdf)
    viewer = window.pdf_viewer
    start = viewport_point(viewer, 0, text_point(viewer))
    end = viewport_point(viewer, 0, text_point(viewer, index=10))

    QTest.mousePress(viewer.viewport(), Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(viewer.viewport(), end)
    QTest.mouseRelease(viewer.viewport(), Qt.LeftButton, Qt.NoModifier, end)

    cursor = viewer.textCursor()
    assert cursor.hasSelection()
    assert viewer.mode == PdfViewer.VISUAL
    assert cursor.selectedText() in "First page first line."


def test_the_pane_reports_which_page_a_point_is_on(qtbot, tmp_path, write_pdf):
    window = open_pdf(qtbot, tmp_path, write_pdf)
    viewer = window.pdf_viewer

    assert viewer.page_at(viewport_point(viewer, 0, text_point(viewer))) == 0
    assert viewer.page_at(QPoint(2, 2)) is None  # the margin around the pages
    assert viewer.nearest_page(QPoint(2, 2)) == 0


def test_a_pane_with_no_document_paints_nothing_and_stays_quiet(qtbot):
    pane = PdfPane()
    qtbot.addWidget(pane)
    pane.show()

    pane.viewer.set_source(None)

    assert pane.viewer.page_count == 0
    assert pane.viewer.page_rect(0).isEmpty()
    assert pane.viewer.region_at(QPoint(5, 5)) is None
