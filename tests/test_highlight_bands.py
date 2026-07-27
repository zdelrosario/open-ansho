from PySide6.QtCore import QRect, QRectF
from PySide6.QtGui import QColor, QTextCursor

from openansho.ui.vim_viewer import CodeHighlight, VimTextViewer


def _make_viewer(qtbot, text="Hello frustrating world.\nSecond line here."):
    viewer = VimTextViewer()
    qtbot.addWidget(viewer)
    viewer.setPlainText(text)
    viewer.moveCursor(QTextCursor.Start)
    viewer.show()
    return viewer


class _FakePainter:
    def __init__(self):
        self.fills = []
        self.strokes = []
        self._pen = None

    def fillRect(self, rect, color):
        self.fills.append((rect, color))

    def setPen(self, pen):
        self._pen = pen

    def drawRect(self, rect):
        self.strokes.append((rect, self._pen))


def test_line_rects_for_range_within_a_single_line(qtbot):
    viewer = _make_viewer(qtbot)
    text = viewer.toPlainText()
    start = text.index("frustrating")
    end = start + len("frustrating")

    rects = viewer._line_rects_for_range(start, end)

    assert len(rects) == 1
    rect = rects[0]
    assert rect.width() > 0
    assert rect.height() > 0
    assert rect.left() < rect.right()


def test_line_rects_for_range_spans_a_hard_line_break(qtbot):
    viewer = _make_viewer(qtbot)
    text = viewer.toPlainText()
    start = text.index("world.")
    end = text.index("line here.") + len("line here.")
    assert "\n" in text[start:end]

    rects = viewer._line_rects_for_range(start, end)

    assert len(rects) == 2
    first_line_rect, second_line_rect = rects
    # Second visual line sits below the first.
    assert second_line_rect.top() > first_line_rect.top()


def test_paint_code_highlight_divides_height_and_offsets_by_band(qtbot, monkeypatch):
    viewer = _make_viewer(qtbot)
    fixed_rect = QRect(10, 100, 40, 20)
    monkeypatch.setattr(viewer, "_line_rects_for_range", lambda start, end: [fixed_rect])

    color = QColor("#ff0000")
    highlight = CodeHighlight(start=0, end=5, color=color, band_index=1, band_count=4)
    painter = _FakePainter()

    viewer._paint_code_highlight(painter, highlight)

    assert len(painter.fills) == 1
    rect, fill_color = painter.fills[0]
    assert fill_color == color
    assert rect == QRectF(10, 105, 40, 5)  # top offset by 1/4, height divided by 4


def test_paint_code_highlight_uses_full_height_for_a_single_band(qtbot, monkeypatch):
    viewer = _make_viewer(qtbot)
    fixed_rect = QRect(0, 0, 30, 16)
    monkeypatch.setattr(viewer, "_line_rects_for_range", lambda start, end: [fixed_rect])

    highlight = CodeHighlight(start=0, end=5, color=QColor("#00ff00"), band_index=0, band_count=1)
    painter = _FakePainter()

    viewer._paint_code_highlight(painter, highlight)

    rect, _ = painter.fills[0]
    assert rect == QRectF(0, 0, 30, 16)


def test_paint_code_highlight_outlines_a_conflicting_segment(qtbot, monkeypatch):
    from openansho.ui.vim_viewer import CONFLICT_OUTLINE_COLOR

    viewer = _make_viewer(qtbot)
    fixed_rect = QRect(10, 100, 40, 20)
    monkeypatch.setattr(viewer, "_line_rects_for_range", lambda start, end: [fixed_rect])

    highlight = CodeHighlight(
        start=0, end=5, color=QColor("#ff0000"), band_index=0, band_count=2, outlined=True
    )
    painter = _FakePainter()

    viewer._paint_code_highlight(painter, highlight)

    assert len(painter.strokes) == 1
    rect, pen = painter.strokes[0]
    assert rect == fixed_rect  # full-height text rect, not the smaller band rect
    assert pen.color() == CONFLICT_OUTLINE_COLOR


def test_paint_code_highlight_does_not_outline_a_non_conflicting_segment(qtbot, monkeypatch):
    viewer = _make_viewer(qtbot)
    fixed_rect = QRect(10, 100, 40, 20)
    monkeypatch.setattr(viewer, "_line_rects_for_range", lambda start, end: [fixed_rect])

    highlight = CodeHighlight(
        start=0, end=5, color=QColor("#ff0000"), band_index=0, band_count=2, outlined=False
    )
    painter = _FakePainter()

    viewer._paint_code_highlight(painter, highlight)

    assert painter.strokes == []
