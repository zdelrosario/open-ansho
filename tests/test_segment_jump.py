"""Double-clicking a coded segment centers it in the document pane."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QListWidgetItem

from openansho.ui.main_window import MainWindow
from test_pdf_regions import FIGURE
from test_pdf_viewer import open_pdf

LINES = [f"Line number {n} of the document." for n in range(300)]


def _activate(window, start, end):
    """Double-click a segment row: the handler only reads the row's data."""
    item = QListWidgetItem()
    item.setData(Qt.UserRole, ("segment", window._current_document_id, start, end, None))
    window._on_segment_activated(item)


def _text_window(qtbot, tmp_path, lines=LINES):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    window.resize(1000, 700)
    window.create_project(tmp_path / "project.sqlite")
    (tmp_path / "doc.txt").write_text("\n".join(lines), encoding="utf-8")
    window.import_document(tmp_path / "doc.txt")
    window.document_list.setCurrentRow(0)
    qtbot.waitExposed(window)
    return window


def _text_span_middle(viewer, start, end):
    first = QTextCursor(viewer.document())
    first.setPosition(start)
    last = QTextCursor(viewer.document())
    last.setPosition(end)
    return (viewer.cursorRect(first).top() + viewer.cursorRect(last).bottom()) / 2


def _offset_of_line(lines, number):
    return sum(len(line) + 1 for line in lines[:number])


def test_a_text_segment_far_below_is_centered(qtbot, tmp_path):
    window = _text_window(qtbot, tmp_path)
    viewer = window.viewer
    start = _offset_of_line(LINES, 200)
    end = start + len(LINES[200])

    _activate(window, start, end)

    line_height = viewer.fontMetrics().lineSpacing()
    middle = viewer.viewport().height() / 2
    assert abs(_text_span_middle(viewer, start, end) - middle) <= line_height
    assert viewer.textCursor().selectedText() == LINES[200]


def test_a_text_segment_already_on_screen_is_still_centered(qtbot, tmp_path):
    window = _text_window(qtbot, tmp_path)
    viewer = window.viewer
    start = _offset_of_line(LINES, 1)  # visible already, near the top
    end = start + len(LINES[1])

    _activate(window, start, end)

    # The first lines can't be scrolled any further down than the top.
    assert viewer.verticalScrollBar().value() == 0

    start = _offset_of_line(LINES, 120)
    end = start + len(LINES[120])
    _activate(window, start, end)  # now 120 sits mid-pane
    start = _offset_of_line(LINES, 125)
    end = start + len(LINES[125])
    _activate(window, start, end)  # on screen, a few lines lower

    line_height = viewer.fontMetrics().lineSpacing()
    middle = viewer.viewport().height() / 2
    assert abs(_text_span_middle(viewer, start, end) - middle) <= line_height


def test_a_text_segment_taller_than_the_pane_starts_at_the_top(qtbot, tmp_path):
    window = _text_window(qtbot, tmp_path)
    viewer = window.viewer
    start = _offset_of_line(LINES, 100)
    end = _offset_of_line(LINES, 250)

    _activate(window, start, end)

    first = QTextCursor(viewer.document())
    first.setPosition(start)
    top = viewer.cursorRect(first).top()
    assert 0 <= top <= viewer.fontMetrics().lineSpacing()


PAGES = [[f"Page {page} line {line}." for line in range(6)] for page in range(6)]


def test_a_pdf_text_segment_is_centered(qtbot, tmp_path, write_pdf):
    window = open_pdf(qtbot, tmp_path, write_pdf, pages=PAGES)
    viewer = window.pdf_viewer
    content = viewer.toPlainText()
    start = content.index("Page 4 line 3.")
    end = start + len("Page 4 line 3.")

    _activate(window, start, end)

    rects = [viewer.from_page_rect(page, rect) for page, rect in viewer._text_map.rects_for_range(start, end)]
    middle = sum(rect.center().y() for rect in rects) / len(rects)
    assert abs(middle - viewer.viewport().height() / 2) <= 2


def test_a_pdf_region_segment_is_centered_on_the_region(qtbot, tmp_path, write_pdf):
    window = open_pdf(qtbot, tmp_path, write_pdf, pages=PAGES)
    viewer = window.pdf_viewer
    region = window.create_region(3, FIGURE)
    viewer.verticalScrollBar().setValue(0)

    _activate(window, region.text_offset, region.text_offset + 1)

    mark = next(mark for mark in viewer.marks if mark.region_id == region.id)
    center = viewer._mark_polygon(mark).boundingRect().center().y()
    assert abs(center - viewer.viewport().height() / 2) <= 2
