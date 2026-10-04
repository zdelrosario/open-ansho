"""The PDF pane: a document's pages, scrolled continuously, with a text cursor.

A PDF gets one pane rather than a page image beside a text pane. The pages
themselves are what the user reads, navigates and codes: the vim cursor sits
on the page, on the actual words, and a selection is painted over them.

That works because the pane keeps the same text every other part of the app
codes against (`documents.content`) in a QTextDocument of its own, and
`pdf_extract.PdfTextMap` maps between an offset in that text and the
rectangle the character occupies on its page. The motions and modes are
`vim_keys.VimTextNavigation`, shared verbatim with the plain-text pane —
minus insert mode, which a PDF can't have: the text is a reading of the
page, so editing it would only make the two disagree.

Parts of a page that aren't text are coded as regions: drag where there is no
text to draw one, as a rectangle or freehand. A region is stored as a polygon
in page fractions and carries one marker character in the text, so coding it
is coding a span like any other.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
    QTextCursor,
    QTextDocument,
)
from PySide6.QtWidgets import (
    QAbstractScrollArea,
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from openansho import pdf_extract
from openansho.ui.highlight_paint import paint_diagonal_stripes
from openansho.ui.vim_keys import VimTextNavigation

PAGE_GAP_PX = 12
PAGE_MARGIN_PX = 8
STRIPE_WIDTH_PX = 10

MIN_ZOOM = 0.25
MAX_ZOOM = 6.0
ZOOM_STEP = 1.25

# Qt's PDF renderer leaves the paper transparent rather than white, so the
# page is painted onto a sheet of its own. White in both themes: the page is
# paper, and dark PDF text on a dark pane would be unreadable.
PAGE_COLOR = QColor(255, 255, 255)
PAGE_EDGE_COLOR = QColor(160, 160, 160)

SELECTION_COLOR = QColor(51, 153, 255)  # matches PANE_FOCUS_STYLE's focus border
TEXT_SELECTION_COLOR = QColor(51, 153, 255, 90)
UNCODED_REGION_COLOR = QColor(130, 130, 130)
REGION_OUTLINE_WIDTH = 1
SELECTED_REGION_OUTLINE_WIDTH = 3
CONFLICT_OUTLINE_COLOR = QColor("red")
CONFLICT_OUTLINE_WIDTH = 2

# A press and release within this many pixels is a click, not a drag.
DRAG_THRESHOLD_PX = 5
# How far back to look for a glyph to hang the caret off, for a character
# that has none of its own (a space, a region marker, a page separator).
CARET_SCAN_LIMIT = 24
# Regions smaller than this fraction of the page in either direction are
# dropped, so a slightly-dragged click leaves no speck behind.
MIN_REGION_FRACTION = 0.01
# Freehand points closer together than this (in viewport pixels) are skipped,
# so a slow drag doesn't store hundreds of near-identical points.
FREEHAND_MIN_STEP_PX = 3

REGION_RECTANGLE = "rectangle"
REGION_FREEHAND = "freehand"


@dataclass(frozen=True)
class RegionMark:
    """One region to draw: where it is, and the colors of its codes.

    `points` is the region's outline in page fractions — a rectangle is just
    its four corners, so rectangle and freehand regions draw and hit-test
    through the same path. `colors` is empty for a region nobody has coded
    yet, which is drawn as a bare dashed outline so it stays visible and
    clickable.
    """

    region_id: int
    page: int
    points: tuple[tuple[float, float], ...]
    colors: tuple[QColor, ...] = field(default_factory=tuple)
    selected: bool = False


def bounding_box(points) -> tuple[float, float, float, float]:
    """(x, y, width, height) of `points`, which are in page fractions."""
    xs = [x for x, _ in points]
    ys = [y for _, y in points]
    return min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)


class PdfViewer(VimTextNavigation, QAbstractScrollArea):
    """The scrolling page view: rendering, the cursor, selections, regions."""

    supports_insert_mode = False

    modeChanged = Signal(str)
    searchTextChanged = Signal(str)
    contentEdited = Signal(int, int, int)  # never emitted; a PDF has no insert mode
    cursorPositionChanged = Signal()
    selectionChanged = Signal()
    zoomChanged = Signal(float)
    regionDrawn = Signal(int, object)  # page, points in page fractions
    regionClicked = Signal(object)  # region_id, or None for empty space
    regionContextMenuRequested = Signal(object, QPoint)  # region_id or None, global pos

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFocusPolicy(Qt.StrongFocus)
        self.viewport().setCursor(Qt.IBeamCursor)

        self._init_vim_state()
        self._source: pdf_extract.PdfPageSource | None = None
        self._text_map: pdf_extract.PdfTextMap | None = None
        self._document = QTextDocument(self)
        self._cursor = QTextCursor(self._document)
        self._code_highlights: list = []
        self._marks: list[RegionMark] = []
        self._zoom = 1.0
        self._region_mode = REGION_RECTANGLE
        self._rendered: dict[int, tuple[QSize, QImage]] = {}
        self._page_tops: list[int] = []
        self._content_size = QSize(0, 0)

        self._press_origin: QPoint | None = None
        self._press_page: int | None = None
        self._press_on_text = False
        self._dragging_text = False
        self._draw_points: list[QPointF] = []  # page fractions, while drawing

        self.set_theme(dark_mode=False)
        self.verticalScrollBar().valueChanged.connect(lambda _v: self.viewport().update())
        self.horizontalScrollBar().valueChanged.connect(lambda _v: self.viewport().update())

    # -- the text behind the pages ------------------------------------------

    def set_source(self, source: pdf_extract.PdfPageSource | None) -> None:
        self._source = source
        self._rendered.clear()
        self._marks = []
        self._code_highlights = []
        self._rebuild_text_map()
        self._relayout()

    def setPlainText(self, text: str) -> None:
        self._document.setPlainText(text)
        self._cursor = QTextCursor(self._document)
        self._rebuild_text_map()
        self.viewport().update()
        self.cursorPositionChanged.emit()
        self.selectionChanged.emit()

    def clear(self) -> None:
        self.setPlainText("")

    def replace_text(self, position: int, length: int, text: str) -> None:
        """Splice `text` in over `length` characters at `position`.

        The counterpart of `VimTextViewer.replace_text`: how a region marker
        gets into the document's text without going through an edit the
        caller then has to reconcile against.
        """
        cursor = QTextCursor(self._document)
        cursor.setPosition(position)
        if length:
            cursor.setPosition(position + length, QTextCursor.KeepAnchor)
        cursor.insertText(text)
        self._rebuild_text_map()
        self.viewport().update()

    def toPlainText(self) -> str:
        return self._document.toPlainText()

    def document(self) -> QTextDocument:
        return self._document

    def textCursor(self) -> QTextCursor:
        return QTextCursor(self._cursor)

    def setTextCursor(self, cursor: QTextCursor) -> None:
        had_selection = self._cursor.hasSelection()
        old_position = self._cursor.position()
        self._cursor = QTextCursor(cursor)
        if self._cursor.position() != old_position:
            self.cursorPositionChanged.emit()
        if self._cursor.hasSelection() or had_selection:
            self.selectionChanged.emit()
        self.ensureCursorVisible()
        self.viewport().update()

    def _rebuild_text_map(self) -> None:
        self._text_map = (
            pdf_extract.PdfTextMap(self.toPlainText(), self._source)
            if self._source is not None
            else None
        )

    # -- appearance ----------------------------------------------------------

    def set_theme(self, dark_mode: bool) -> None:
        self._dark_mode = dark_mode
        self.viewport().update()

    def set_code_highlights(self, highlights: list) -> None:
        self._code_highlights = list(highlights)
        self.viewport().update()

    def set_region_marks(self, marks: list[RegionMark]) -> None:
        self._marks = list(marks)
        self.viewport().update()

    @property
    def marks(self) -> list[RegionMark]:
        return list(self._marks)

    @property
    def page_count(self) -> int:
        return self._source.page_count if self._source is not None else 0

    # -- zoom ----------------------------------------------------------------

    @property
    def zoom(self) -> float:
        return self._zoom

    def set_zoom(self, zoom: float) -> None:
        zoom = max(MIN_ZOOM, min(zoom, MAX_ZOOM))
        if abs(zoom - self._zoom) < 1e-6:
            return
        # Keep whatever is in the middle of the viewport in the middle of it.
        anchor = self._viewport_center_in_content()
        self._zoom = zoom
        self._rendered.clear()
        self._relayout()
        self._restore_center(anchor, zoom)
        self.zoomChanged.emit(self._zoom)
        self.viewport().update()

    def zoom_in(self) -> None:
        self.set_zoom(self._zoom * ZOOM_STEP)

    def zoom_out(self) -> None:
        self.set_zoom(self._zoom / ZOOM_STEP)

    def _viewport_center_in_content(self) -> tuple[float, float]:
        width = max(self._content_size.width(), 1)
        height = max(self._content_size.height(), 1)
        x = (self.horizontalScrollBar().value() + self.viewport().width() / 2) / width
        y = (self.verticalScrollBar().value() + self.viewport().height() / 2) / height
        return x, y

    def _restore_center(self, anchor: tuple[float, float], _zoom: float) -> None:
        x, y = anchor
        self.horizontalScrollBar().setValue(
            int(x * self._content_size.width() - self.viewport().width() / 2)
        )
        self.verticalScrollBar().setValue(
            int(y * self._content_size.height() - self.viewport().height() / 2)
        )

    def wheelEvent(self, event) -> None:
        if event.modifiers() & Qt.ControlModifier:
            steps = event.angleDelta().y() / 120.0
            if steps:
                self.set_zoom(self._zoom * (ZOOM_STEP ** steps))
            event.accept()
            return
        super().wheelEvent(event)

    # -- layout --------------------------------------------------------------

    def _relayout(self) -> None:
        """Stack the pages vertically and resize the scrollbars to fit them."""
        self._page_tops = []
        if self._source is None:
            self._content_size = QSize(0, 0)
        else:
            y = PAGE_MARGIN_PX
            widest = 0
            for page in range(self._source.page_count):
                size = self._page_pixel_size(page)
                self._page_tops.append(y)
                y += size.height() + PAGE_GAP_PX
                widest = max(widest, size.width())
            self._content_size = QSize(
                widest + 2 * PAGE_MARGIN_PX, y - PAGE_GAP_PX + PAGE_MARGIN_PX
            )
        self._update_scrollbars()
        self.viewport().update()

    def _page_pixel_size(self, page: int) -> QSize:
        size = self._source.page_size(page)
        return QSize(
            max(int(size.width() * self._zoom), 1), max(int(size.height() * self._zoom), 1)
        )

    def _update_scrollbars(self) -> None:
        viewport = self.viewport().size()
        for bar, extent, span in (
            (self.horizontalScrollBar(), self._content_size.width(), viewport.width()),
            (self.verticalScrollBar(), self._content_size.height(), viewport.height()),
        ):
            bar.setRange(0, max(0, extent - span))
            bar.setPageStep(span)
            bar.setSingleStep(max(span // 10, 1))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_scrollbars()

    def _scroll_offset(self) -> QPoint:
        return QPoint(self.horizontalScrollBar().value(), self.verticalScrollBar().value())

    def page_rect(self, page: int) -> QRect:
        """Where a page sits in viewport coordinates."""
        if self._source is None or page >= len(self._page_tops):
            return QRect()
        size = self._page_pixel_size(page)
        left = (self._content_size.width() - size.width()) // 2
        offset = self._scroll_offset()
        return QRect(
            left - offset.x(), self._page_tops[page] - offset.y(), size.width(), size.height()
        )

    def _visible_pages(self) -> list[int]:
        bottom = self.viewport().height()
        pages = []
        for page in range(self.page_count):
            rect = self.page_rect(page)
            if rect.bottom() < 0:
                continue
            if rect.top() > bottom:
                break
            pages.append(page)
        return pages

    def page_at(self, point: QPoint) -> int | None:
        """Which page `point` (viewport coordinates) falls on, if any."""
        for page in range(self.page_count):
            if self.page_rect(page).contains(point):
                return page
        return None

    def nearest_page(self, point: QPoint) -> int:
        """Like `page_at`, but never None: the closest page vertically."""
        best, best_distance = 0, None
        for page in range(self.page_count):
            rect = self.page_rect(page)
            if rect.contains(point):
                return page
            distance = min(abs(point.y() - rect.top()), abs(point.y() - rect.bottom()))
            if best_distance is None or distance < best_distance:
                best, best_distance = page, distance
        return best

    def to_page_point(self, page: int, point: QPoint) -> QPointF:
        """A viewport point in the page's own coordinates (PDF points)."""
        rect = self.page_rect(page)
        return QPointF((point.x() - rect.x()) / self._zoom, (point.y() - rect.y()) / self._zoom)

    def to_page_fraction(self, page: int, point: QPoint) -> tuple[float, float]:
        rect = self.page_rect(page)
        if rect.isEmpty():
            return 0.0, 0.0
        x = (point.x() - rect.x()) / rect.width()
        y = (point.y() - rect.y()) / rect.height()
        return min(max(x, 0.0), 1.0), min(max(y, 0.0), 1.0)

    def from_page_rect(self, page: int, rect: QRectF) -> QRectF:
        """A rectangle in page points, in viewport coordinates."""
        page_rect = self.page_rect(page)
        return QRectF(
            page_rect.x() + rect.x() * self._zoom,
            page_rect.y() + rect.y() * self._zoom,
            rect.width() * self._zoom,
            rect.height() * self._zoom,
        )

    def _mark_polygon(self, mark: RegionMark) -> QPolygonF:
        rect = self.page_rect(mark.page)
        return QPolygonF(
            [
                QPointF(rect.x() + x * rect.width(), rect.y() + y * rect.height())
                for x, y in mark.points
            ]
        )

    def region_at(self, point: QPoint) -> int | None:
        """The smallest region whose outline contains `point`, if any."""
        hits = []
        for mark in self._marks:
            polygon = self._mark_polygon(mark)
            if polygon.containsPoint(QPointF(point), Qt.OddEvenFill):
                hits.append((polygon.boundingRect().width() * polygon.boundingRect().height(), mark))
        if not hits:
            return None
        return min(hits, key=lambda pair: pair[0])[1].region_id

    # -- the motions that depend on the layout -------------------------------

    def _cursor_rect(self, position: int | None = None) -> QRectF:
        """Viewport rectangle of the character at `position`.

        A character with no glyph of its own — a region marker, a page
        separator, the newline at the end of a line — gets a narrow caret
        just past the previous glyph instead, so the cursor stays visible
        wherever a motion puts it.
        """
        if self._text_map is None:
            return QRectF()
        if position is None:
            position = self._cursor.position()
        located = self._text_map.rect_for_offset(position)
        if located is not None:
            page, rect = located
            return self.from_page_rect(page, rect)

        page = self._text_map.page_for_offset(position)
        start, _end = self._text_map.page_range(page)
        # Bounded: each step that finds nothing costs a call into the PDF,
        # and a cursor sitting before any glyph on its page would otherwise
        # walk the whole page asking about every character.
        for previous in range(position - 1, max(start, position - CARET_SCAN_LIMIT) - 1, -1):
            located = self._text_map.rect_for_offset(previous)
            if located is not None:
                found_page, rect = located
                caret = QRectF(rect.right(), rect.top(), max(rect.height() * 0.4, 1.0), rect.height())
                return self.from_page_rect(found_page, caret)
        page_rect = self.page_rect(page)
        return QRectF(page_rect.x(), page_rect.y(), 2, 12 * self._zoom)

    def ensureCursorVisible(self) -> None:
        rect = self._cursor_rect()
        if rect.isEmpty():
            return
        offset = self._scroll_offset()
        viewport = self.viewport().rect()
        if rect.top() < 0:
            self.verticalScrollBar().setValue(int(offset.y() + rect.top()))
        elif rect.bottom() > viewport.height():
            self.verticalScrollBar().setValue(int(offset.y() + rect.bottom() - viewport.height()))
        if rect.left() < 0:
            self.horizontalScrollBar().setValue(int(offset.x() + rect.left()))
        elif rect.right() > viewport.width():
            self.horizontalScrollBar().setValue(int(offset.x() + rect.right() - viewport.width()))

    def centerCursor(self) -> None:
        rect = self._cursor_rect()
        if rect.isEmpty():
            return
        offset = self._scroll_offset()
        self.verticalScrollBar().setValue(
            int(offset.y() + rect.center().y() - self.viewport().height() / 2)
        )

    def _visible_line_starts(self) -> list[int]:
        """Offsets of the first character of each line currently on screen."""
        starts = []
        height = self.viewport().height()
        for page in self._visible_pages():
            start, end = self._text_map.page_range(page) if self._text_map else (0, 0)
            block = self._document.findBlock(start)
            while block.isValid() and block.position() < end:
                rect = self._cursor_rect(block.position())
                if not rect.isEmpty() and 0 <= rect.top() <= height:
                    starts.append(block.position())
                block = block.next()
        return starts

    def _line_height(self) -> int:
        rect = self._cursor_rect()
        return max(int(rect.height()), 1) if not rect.isEmpty() else 16

    def _scroll_current_line_to_top(self) -> None:
        rect = self._cursor_rect()
        if rect.isEmpty():
            return
        self.verticalScrollBar().setValue(int(self._scroll_offset().y() + rect.top()))

    def _scroll_current_line_to_bottom(self) -> None:
        rect = self._cursor_rect()
        if rect.isEmpty():
            return
        self.verticalScrollBar().setValue(
            int(self._scroll_offset().y() + rect.bottom() - self.viewport().height())
        )

    def _scroll_viewport_lines(self, delta: int) -> None:
        bar = self.verticalScrollBar()
        bar.setValue(bar.value() + delta * self._line_height())

    # -- mouse ---------------------------------------------------------------

    @property
    def region_mode(self) -> str:
        return self._region_mode

    def set_region_mode(self, mode: str) -> None:
        self._region_mode = mode

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.LeftButton or self._source is None:
            super().mousePressEvent(event)
            return
        point = event.position().toPoint()
        page = self.page_at(point)
        self._press_origin = point
        self._press_page = page
        self._dragging_text = False
        self._draw_points = []
        self._press_on_text = page is not None and self._text_map is not None and (
            self._text_map.is_over_text(page, self.to_page_point(page, point))
        )
        if self._press_on_text:
            # A press on a word puts the cursor there; dragging from it
            # selects, exactly as dragging in the text pane does.
            self.exit_visual_mode()
            offset = self._text_map.offset_at(page, self.to_page_point(page, point))
            cursor = self.textCursor()
            cursor.setPosition(offset)
            self.setTextCursor(cursor)
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._press_origin is None:
            super().mouseMoveEvent(event)
            return
        point = event.position().toPoint()
        delta = point - self._press_origin
        if max(abs(delta.x()), abs(delta.y())) < DRAG_THRESHOLD_PX and not self._dragging_text:
            event.accept()
            return

        if self._press_on_text:
            self._dragging_text = True
            self._extend_selection_to(point)
        elif self._press_page is not None:
            self._record_draw_point(point)
        self.viewport().update()
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if self._press_origin is None or event.button() != Qt.LeftButton:
            super().mouseReleaseEvent(event)
            return
        origin, self._press_origin = self._press_origin, None
        page, self._press_page = self._press_page, None
        on_text, self._press_on_text = self._press_on_text, False
        dragging, self._dragging_text = self._dragging_text, False
        points, self._draw_points = self._draw_points, []

        point = event.position().toPoint()
        delta = point - origin
        was_drag = max(abs(delta.x()), abs(delta.y())) >= DRAG_THRESHOLD_PX

        if on_text:
            if dragging:
                self._extend_selection_to(point)
        elif not was_drag:
            self.regionClicked.emit(self.region_at(point))
        elif page is not None:
            self._finish_region(page, points, origin, point)
        self.viewport().update()
        event.accept()

    def _extend_selection_to(self, point: QPoint) -> None:
        page = self.nearest_page(point)
        if self._text_map is None:
            return
        offset = self._text_map.offset_at(page, self.to_page_point(page, point))
        self._enter_visual_mode()
        cursor = self.textCursor()
        cursor.setPosition(cursor.anchor())
        cursor.setPosition(offset, QTextCursor.KeepAnchor)
        self.setTextCursor(cursor)

    def _record_draw_point(self, point: QPoint) -> None:
        if self._region_mode == REGION_RECTANGLE:
            # Only the latest corner matters; the rectangle is origin to here.
            self._draw_points = [QPointF(point)]
            return
        if self._draw_points:
            last = self._draw_points[-1]
            if (abs(last.x() - point.x()) + abs(last.y() - point.y())) < FREEHAND_MIN_STEP_PX:
                return
        self._draw_points.append(QPointF(point))

    def _finish_region(self, page: int, points, origin: QPoint, release: QPoint) -> None:
        if self._region_mode == REGION_RECTANGLE:
            rect = QRect(origin, release).normalized()
            corners = [rect.topLeft(), rect.topRight(), rect.bottomRight(), rect.bottomLeft()]
            fractions = [self.to_page_fraction(page, corner) for corner in corners]
        else:
            path = [origin, *(point.toPoint() for point in points), release]
            fractions = [self.to_page_fraction(page, point) for point in path]
            if len(fractions) < 3:
                return
        _x, _y, width, height = bounding_box(fractions)
        if width < MIN_REGION_FRACTION or height < MIN_REGION_FRACTION:
            return
        self.regionDrawn.emit(page, fractions)

    def contextMenuEvent(self, event) -> None:
        if self._source is None:
            super().contextMenuEvent(event)
            return
        self.regionContextMenuRequested.emit(self.region_at(event.pos()), event.globalPos())
        event.accept()

    # -- painting ------------------------------------------------------------

    def paintEvent(self, event) -> None:
        painter = QPainter(self.viewport())
        if self._source is None:
            painter.end()
            return

        for page in self._visible_pages():
            rect = self.page_rect(page)
            painter.fillRect(rect, PAGE_COLOR)
            image = self._page_image(page, rect.size())
            if image is not None and not image.isNull():
                painter.drawImage(rect, image)
            painter.setPen(QPen(PAGE_EDGE_COLOR))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(rect.adjusted(0, 0, -1, -1))

        for highlight in self._code_highlights:
            self._paint_code_highlight(painter, highlight)
        for mark in self._marks:
            self._paint_region(painter, mark)
        self._paint_selection(painter)
        self._paint_cursor(painter)
        self._paint_draft(painter)
        painter.end()

    def _page_image(self, page: int, size: QSize) -> QImage | None:
        ratio = self.devicePixelRatio()
        wanted = QSize(int(size.width() * ratio), int(size.height() * ratio))
        cached = self._rendered.get(page)
        if cached is None or cached[0] != wanted:
            image = self._source.render(page, wanted)
            if image is not None and not image.isNull():
                image.setDevicePixelRatio(ratio)
            self._rendered[page] = (wanted, image)
            cached = self._rendered[page]
        return cached[1]

    def _paint_code_highlight(self, painter: QPainter, highlight) -> None:
        if self._text_map is None:
            return
        for page, rect in self._text_map.rects_for_range(highlight.start, highlight.end):
            full = self.from_page_rect(page, rect)
            band_height = full.height() / highlight.band_count
            band = QRectF(
                full.left(),
                full.top() + highlight.band_index * band_height,
                full.width(),
                band_height,
            )
            if highlight.stripe_colors:
                paint_diagonal_stripes(painter, band, highlight.stripe_colors, STRIPE_WIDTH_PX)
            else:
                painter.fillRect(band, highlight.color)
            if highlight.outlined:
                pen = QPen(CONFLICT_OUTLINE_COLOR)
                pen.setWidth(CONFLICT_OUTLINE_WIDTH)
                painter.setPen(pen)
                painter.setBrush(Qt.NoBrush)
                painter.drawRect(full)

    def _paint_region(self, painter: QPainter, mark: RegionMark) -> None:
        polygon = self._mark_polygon(mark)
        if polygon.isEmpty():
            return
        path = QPainterPath()
        path.addPolygon(polygon)
        path.closeSubpath()

        if len(mark.colors) > 1:
            painter.save()
            painter.setClipPath(path)
            paint_diagonal_stripes(
                painter, polygon.boundingRect(), mark.colors, STRIPE_WIDTH_PX
            )
            painter.restore()
        elif mark.colors:
            painter.fillPath(path, mark.colors[0])

        if mark.selected:
            pen = QPen(SELECTION_COLOR)
            pen.setWidth(SELECTED_REGION_OUTLINE_WIDTH)
        elif mark.colors:
            solid = QColor(mark.colors[0])
            solid.setAlpha(255)
            pen = QPen(solid)
            pen.setWidth(REGION_OUTLINE_WIDTH)
        else:
            pen = QPen(UNCODED_REGION_COLOR)
            pen.setWidth(REGION_OUTLINE_WIDTH)
            pen.setStyle(Qt.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)

    def _paint_selection(self, painter: QPainter) -> None:
        if self._text_map is None or not self._cursor.hasSelection():
            return
        start, end = self._cursor.selectionStart(), self._cursor.selectionEnd()
        for page, rect in self._text_map.rects_for_range(start, end):
            painter.fillRect(self.from_page_rect(page, rect), TEXT_SELECTION_COLOR)

    def _paint_cursor(self, painter: QPainter) -> None:
        if self._text_map is None or self._cursor.hasSelection():
            return
        rect = self._cursor_rect()
        if rect.isEmpty():
            return
        painter.fillRect(rect, QColor(0, 0, 0, 90))
        pen = QPen(QColor(0, 0, 0))
        pen.setWidth(1)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(rect)

    def _paint_draft(self, painter: QPainter) -> None:
        """The region being dragged out right now."""
        if self._press_origin is None or self._press_on_text:
            return
        pen = QPen(SELECTION_COLOR)
        pen.setWidth(REGION_OUTLINE_WIDTH)
        pen.setStyle(Qt.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        if self._region_mode == REGION_RECTANGLE:
            if self._draw_points:
                painter.drawRect(
                    QRect(self._press_origin, self._draw_points[-1].toPoint()).normalized()
                )
        elif self._draw_points:
            polygon = QPolygonF([QPointF(self._press_origin), *self._draw_points])
            painter.drawPolyline(polygon)
            painter.drawLine(polygon.first(), polygon.last())


class PdfPane(QWidget):
    """`PdfViewer` plus the bar of zoom and region-tool buttons beneath it."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        self.viewer = PdfViewer()
        self.viewer.setObjectName("pdfViewerPane")
        self.viewer.zoomChanged.connect(lambda _z: self._update_zoom_label())

        self.zoom_out_button = QPushButton("−")
        self.zoom_out_button.setToolTip("Zoom out (Ctrl+scroll)")
        self.zoom_out_button.clicked.connect(self.viewer.zoom_out)
        self.zoom_in_button = QPushButton("+")
        self.zoom_in_button.setToolTip("Zoom in (Ctrl+scroll)")
        self.zoom_in_button.clicked.connect(self.viewer.zoom_in)
        self.zoom_label = QLabel()

        self.rectangle_button = QPushButton("▭ Rectangle")
        self.rectangle_button.setToolTip("Drag out rectangular regions off the text")
        self.freehand_button = QPushButton("✎ Freehand")
        self.freehand_button.setToolTip(
            "Draw regions freehand: hold and draw, release to close the shape"
        )
        self._tools = QButtonGroup(self)
        self._tools.setExclusive(True)
        for button, mode in (
            (self.rectangle_button, REGION_RECTANGLE),
            (self.freehand_button, REGION_FREEHAND),
        ):
            button.setCheckable(True)
            self._tools.addButton(button)
            button.clicked.connect(lambda _checked=False, m=mode: self.set_region_mode(m))
        self.rectangle_button.setChecked(True)

        # None of the buttons take focus, so using one leaves the keyboard
        # on the pages where the coding shortcuts expect it.
        for widget in (
            self.zoom_out_button,
            self.zoom_in_button,
            self.rectangle_button,
            self.freehand_button,
        ):
            widget.setFocusPolicy(Qt.NoFocus)

        bar = QHBoxLayout()
        bar.addWidget(self.zoom_out_button)
        bar.addWidget(self.zoom_label)
        bar.addWidget(self.zoom_in_button)
        bar.addStretch()
        bar.addWidget(self.rectangle_button)
        bar.addWidget(self.freehand_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.viewer, 1)
        layout.addLayout(bar)
        self._update_zoom_label()

    def set_region_mode(self, mode: str) -> None:
        self.viewer.set_region_mode(mode)
        self.rectangle_button.setChecked(mode == REGION_RECTANGLE)
        self.freehand_button.setChecked(mode == REGION_FREEHAND)

    @property
    def region_mode(self) -> str:
        return self.viewer.region_mode

    def _update_zoom_label(self) -> None:
        self.zoom_label.setText(f"{round(self.viewer.zoom * 100)}%")
