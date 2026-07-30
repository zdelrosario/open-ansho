from PySide6.QtCore import QRect, QRectF
from PySide6.QtGui import QColor, QTextCursor

from openansho.ui.vim_viewer import STRIPE_WIDTH_IN_CHARS, CodeHighlight, VimTextViewer


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
        self.polygons = []
        self.clip_rects = []
        self._pen = None
        self._brush = None

    def save(self):
        pass

    def restore(self):
        pass

    def setClipRect(self, rect, mode=None):
        self.clip_rects.append((rect, mode))

    def fillRect(self, rect, color):
        self.fills.append((rect, color))

    def setPen(self, pen):
        self._pen = pen

    def setBrush(self, brush):
        self._brush = brush

    def drawRect(self, rect):
        self.strokes.append((rect, self._pen))

    def drawPolygon(self, polygon):
        self.polygons.append((polygon, self._brush))


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


def test_paint_code_highlight_stripes_instead_of_filling_when_multiple_colors(qtbot, monkeypatch):
    viewer = _make_viewer(qtbot)
    fixed_rect = QRect(0, 0, 200, 20)
    monkeypatch.setattr(viewer, "_line_rects_for_range", lambda start, end: [fixed_rect])

    red, green = QColor("#ff0000"), QColor("#00ff00")
    highlight = CodeHighlight(
        start=0, end=5, color=red, band_index=0, band_count=1, stripe_colors=(red, green)
    )
    painter = _FakePainter()

    viewer._paint_code_highlight(painter, highlight)

    assert painter.fills == []  # striped, not a solid fill
    assert len(painter.polygons) > 1


def test_paint_diagonal_stripes_cycles_through_colors_in_order(qtbot):
    viewer = _make_viewer(qtbot)
    rect = QRectF(0, 0, 200, 20)
    colors = (QColor("#ff0000"), QColor("#00ff00"), QColor("#0000ff"))
    painter = _FakePainter()

    viewer._paint_diagonal_stripes(painter, rect, colors)

    brushes = [brush for _, brush in painter.polygons]
    assert len(brushes) > len(colors)
    assert brushes[0] == colors[0]
    assert brushes[1] == colors[1]
    assert brushes[2] == colors[2]
    assert brushes[3] == colors[0]  # cycles back around


def test_paint_diagonal_stripes_are_roughly_two_characters_wide(qtbot):
    viewer = _make_viewer(qtbot)
    rect = QRectF(0, 0, 200, 20)
    painter = _FakePainter()

    viewer._paint_diagonal_stripes(painter, rect, (QColor("red"), QColor("green")))

    expected_width = viewer.fontMetrics().averageCharWidth() * STRIPE_WIDTH_IN_CHARS
    # Every polygon's bottom edge spans exactly one stripe width.
    for polygon, _ in painter.polygons:
        bottom_xs = sorted(p.x() for p in polygon if abs(p.y() - rect.bottom()) < 1e-6)
        assert len(bottom_xs) == 2
        assert abs((bottom_xs[1] - bottom_xs[0]) - expected_width) < 0.01


def test_paint_diagonal_stripes_clips_to_the_given_rect(qtbot):
    viewer = _make_viewer(qtbot)
    rect = QRectF(10, 5, 40, 20)
    painter = _FakePainter()

    viewer._paint_diagonal_stripes(painter, rect, (QColor("red"), QColor("green")))

    assert painter.clip_rects
    assert painter.clip_rects[0][0] == rect
