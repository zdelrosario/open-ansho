"""The PDF page pane: one rendered page, with its coded regions drawn on it.

Shown beside the text pane while a PDF document is open. The text pane still
owns coding and navigation — this pane exists so the parts of a page that
aren't text can be coded too: dragging out a rectangle on the page creates a
region, clicking one selects it, and once selected it is coded exactly like a
selected span of text (see `MainWindow.create_region`).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import QPoint, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from openansho.pdf_extract import PdfPageSource
from openansho.ui.highlight_paint import paint_diagonal_stripes

PAGE_MARGIN_PX = 8
STRIPE_WIDTH_PX = 10

# Qt's PDF renderer leaves the paper transparent rather than white, so the
# page is painted onto a sheet of its own. White in both themes: the page is
# paper, and dark PDF text on a dark pane would be unreadable.
PAGE_COLOR = QColor(255, 255, 255)
PAGE_EDGE_COLOR = QColor(160, 160, 160)

UNCODED_OUTLINE_COLOR = QColor(130, 130, 130)
SELECTION_COLOR = QColor(51, 153, 255)  # matches PANE_FOCUS_STYLE's focus border
OUTLINE_WIDTH = 1
SELECTED_OUTLINE_WIDTH = 3

# A press-and-release within this many pixels is a click (select the region
# under the cursor) rather than a rectangle being dragged out.
DRAG_THRESHOLD_PX = 5

# Rectangles smaller than this fraction of the page in either direction are
# discarded, so a slightly-dragged click doesn't leave a speck behind.
MIN_REGION_FRACTION = 0.01


@dataclass(frozen=True)
class RegionMark:
    """One region to draw: where it is, and the colors of its codes.

    `colors` is empty for a region nobody has coded yet, which is drawn as a
    bare dashed outline so it's still visible and clickable.
    """

    region_id: int
    rect: QRectF  # fractions of the page, as stored in db.Region
    colors: tuple[QColor, ...] = field(default_factory=tuple)
    selected: bool = False


class PdfPageCanvas(QWidget):
    """The page image itself, plus region drawing and hit-testing."""

    regionDrawn = Signal(int, QRectF)  # page, rect in page fractions
    regionClicked = Signal(object)  # region_id, or None for empty space
    regionContextMenuRequested = Signal(object, QPoint)  # region_id or None, global pos

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(120)
        self.setMouseTracking(True)
        self.setCursor(Qt.CrossCursor)

        self._source: PdfPageSource | None = None
        self._page = 0
        self._marks: list[RegionMark] = []
        self._rendered: QImage | None = None
        self._rendered_key: tuple[int, int, int] | None = None
        self._drag_origin: QPoint | None = None
        self._drag_current: QPoint | None = None

    # -- content -------------------------------------------------------------

    def set_source(self, source: PdfPageSource | None) -> None:
        self._source = source
        self._page = 0
        self._marks = []
        self._invalidate_render()

    def set_page(self, page: int) -> None:
        page = self._clamp_page(page)
        if page == self._page:
            return
        self._page = page
        self._invalidate_render()

    @property
    def page(self) -> int:
        return self._page

    @property
    def page_count(self) -> int:
        return self._source.page_count if self._source is not None else 0

    def set_marks(self, marks: list[RegionMark]) -> None:
        self._marks = list(marks)
        self.update()

    @property
    def marks(self) -> list[RegionMark]:
        return list(self._marks)

    def _clamp_page(self, page: int) -> int:
        return max(0, min(page, max(self.page_count - 1, 0)))

    def _invalidate_render(self) -> None:
        self._rendered = None
        self._rendered_key = None
        self.update()

    # -- geometry ------------------------------------------------------------

    def page_rect(self) -> QRect:
        """Where the page is drawn inside this widget, letterboxed and centered."""
        available = self.rect().adjusted(
            PAGE_MARGIN_PX, PAGE_MARGIN_PX, -PAGE_MARGIN_PX, -PAGE_MARGIN_PX
        )
        if self._source is None or available.width() <= 0 or available.height() <= 0:
            return QRect()
        size = self._source.page_size(self._page)
        if size.width() <= 0 or size.height() <= 0:
            return QRect()
        scale = min(
            available.width() / size.width(), available.height() / size.height()
        )
        width = max(int(size.width() * scale), 1)
        height = max(int(size.height() * scale), 1)
        return QRect(
            available.x() + (available.width() - width) // 2,
            available.y() + (available.height() - height) // 2,
            width,
            height,
        )

    def to_page_fractions(self, rect: QRect) -> QRectF:
        """Turn a rect in widget coordinates into fractions of the page."""
        page_rect = self.page_rect()
        if page_rect.isEmpty():
            return QRectF()
        normalized = QRectF(
            (rect.x() - page_rect.x()) / page_rect.width(),
            (rect.y() - page_rect.y()) / page_rect.height(),
            rect.width() / page_rect.width(),
            rect.height() / page_rect.height(),
        )
        return _clamped_to_unit_square(normalized)

    def from_page_fractions(self, rect: QRectF) -> QRect:
        page_rect = self.page_rect()
        if page_rect.isEmpty():
            return QRect()
        return QRectF(
            page_rect.x() + rect.x() * page_rect.width(),
            page_rect.y() + rect.y() * page_rect.height(),
            rect.width() * page_rect.width(),
            rect.height() * page_rect.height(),
        ).toRect()

    def region_at(self, pos: QPoint) -> int | None:
        """The id of the smallest region containing `pos`, if any.

        Smallest, so a region drawn inside a larger one stays reachable.
        """
        hits = [
            mark
            for mark in self._marks
            if self.from_page_fractions(mark.rect).contains(pos)
        ]
        if not hits:
            return None
        return min(hits, key=lambda mark: mark.rect.width() * mark.rect.height()).region_id

    # -- mouse ---------------------------------------------------------------

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.LeftButton or self._source is None:
            super().mousePressEvent(event)
            return
        self._drag_origin = event.position().toPoint()
        self._drag_current = self._drag_origin
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._drag_origin is None:
            super().mouseMoveEvent(event)
            return
        self._drag_current = event.position().toPoint()
        self.update()
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if self._drag_origin is None or event.button() != Qt.LeftButton:
            super().mouseReleaseEvent(event)
            return
        origin, self._drag_origin = self._drag_origin, None
        self._drag_current = None
        release = event.position().toPoint()
        self.update()

        delta = release - origin
        if max(abs(delta.x()), abs(delta.y())) < DRAG_THRESHOLD_PX:
            self.regionClicked.emit(self.region_at(release))
            event.accept()
            return

        rect = self.to_page_fractions(QRect(origin, release).normalized())
        if rect.width() >= MIN_REGION_FRACTION and rect.height() >= MIN_REGION_FRACTION:
            self.regionDrawn.emit(self._page, rect)
        event.accept()

    def contextMenuEvent(self, event) -> None:
        if self._source is None:
            super().contextMenuEvent(event)
            return
        self.regionContextMenuRequested.emit(
            self.region_at(event.pos()), event.globalPos()
        )
        event.accept()

    # -- painting ------------------------------------------------------------

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        page_rect = self.page_rect()
        if self._source is None or page_rect.isEmpty():
            painter.end()
            return

        painter.fillRect(page_rect, PAGE_COLOR)
        image = self._page_image(page_rect.size())
        if image is not None and not image.isNull():
            painter.drawImage(page_rect, image)
        painter.setPen(QPen(PAGE_EDGE_COLOR))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(page_rect.adjusted(0, 0, -1, -1))

        for mark in self._marks:
            self._paint_mark(painter, mark)

        if self._drag_origin is not None and self._drag_current is not None:
            pen = QPen(SELECTION_COLOR)
            pen.setWidth(OUTLINE_WIDTH)
            pen.setStyle(Qt.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(QRect(self._drag_origin, self._drag_current).normalized())
        painter.end()

    def _page_image(self, size: QSize) -> QImage | None:
        ratio = self.devicePixelRatio()
        key = (self._page, int(size.width() * ratio), int(size.height() * ratio))
        if self._rendered_key != key:
            self._rendered = self._source.render(self._page, QSize(key[1], key[2]))
            if self._rendered is not None and not self._rendered.isNull():
                self._rendered.setDevicePixelRatio(ratio)
            self._rendered_key = key
        return self._rendered

    def _paint_mark(self, painter: QPainter, mark: RegionMark) -> None:
        rect = self.from_page_fractions(mark.rect)
        if rect.isEmpty():
            return
        if len(mark.colors) > 1:
            paint_diagonal_stripes(
                painter, QRectF(rect), mark.colors, STRIPE_WIDTH_PX
            )
        elif mark.colors:
            painter.fillRect(rect, mark.colors[0])

        if mark.selected:
            pen = QPen(SELECTION_COLOR)
            pen.setWidth(SELECTED_OUTLINE_WIDTH)
        elif mark.colors:
            pen = QPen(_opaque(mark.colors[0]))
            pen.setWidth(OUTLINE_WIDTH)
        else:
            pen = QPen(UNCODED_OUTLINE_COLOR)
            pen.setWidth(OUTLINE_WIDTH)
            pen.setStyle(Qt.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(rect)


class PdfPageView(QWidget):
    """`PdfPageCanvas` plus a page counter and previous/next page buttons."""

    regionDrawn = Signal(int, QRectF)
    regionClicked = Signal(object)
    regionContextMenuRequested = Signal(object, QPoint)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        self.canvas = PdfPageCanvas()
        self.canvas.setObjectName("pdfPagePane")
        self.canvas.regionDrawn.connect(self.regionDrawn)
        self.canvas.regionClicked.connect(self.regionClicked)
        self.canvas.regionContextMenuRequested.connect(self.regionContextMenuRequested)

        self.previous_page_button = QPushButton("‹")
        self.previous_page_button.setToolTip("Previous page")
        self.previous_page_button.clicked.connect(lambda: self.step_page(-1))
        self.next_page_button = QPushButton("›")
        self.next_page_button.setToolTip("Next page")
        self.next_page_button.clicked.connect(lambda: self.step_page(1))
        self.page_label = QLabel()
        self.page_label.setAlignment(Qt.AlignCenter)

        nav = QHBoxLayout()
        nav.addStretch()
        nav.addWidget(self.previous_page_button)
        nav.addWidget(self.page_label)
        nav.addWidget(self.next_page_button)
        nav.addStretch()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("PDF Page"))
        layout.addWidget(self.canvas, 1)
        layout.addLayout(nav)

        self._update_nav()

    def set_source(self, source: PdfPageSource | None) -> None:
        self.canvas.set_source(source)
        self._update_nav()

    def set_page(self, page: int) -> None:
        self.canvas.set_page(page)
        self._update_nav()

    def step_page(self, delta: int) -> None:
        self.set_page(self.canvas.page + delta)

    def set_marks(self, marks: list[RegionMark]) -> None:
        self.canvas.set_marks(marks)

    @property
    def marks(self) -> list[RegionMark]:
        return self.canvas.marks

    @property
    def page(self) -> int:
        return self.canvas.page

    @property
    def page_count(self) -> int:
        return self.canvas.page_count

    def _update_nav(self) -> None:
        count = self.canvas.page_count
        page = self.canvas.page
        self.page_label.setText(f"{page + 1} / {count}" if count else "—")
        self.previous_page_button.setEnabled(page > 0)
        self.next_page_button.setEnabled(page + 1 < count)


def _clamped_to_unit_square(rect: QRectF) -> QRectF:
    left = min(max(rect.left(), 0.0), 1.0)
    top = min(max(rect.top(), 0.0), 1.0)
    right = min(max(rect.right(), 0.0), 1.0)
    bottom = min(max(rect.bottom(), 0.0), 1.0)
    return QRectF(left, top, right - left, bottom - top)


def _opaque(color: QColor) -> QColor:
    solid = QColor(color)
    solid.setAlpha(255)
    return solid
