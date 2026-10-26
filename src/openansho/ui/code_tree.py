from __future__ import annotations

from PySide6.QtCore import QElapsedTimer, QPointF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QDragMoveEvent, QLinearGradient, QPainter
from PySide6.QtWidgets import QAbstractItemView, QTreeWidget

# Translucent so the code underneath (and Qt's drop indicator on it) stays
# readable; mid-grey reads as a shadow on both the light and dark themes.
SCROLL_ZONE_SHADE = QColor(128, 128, 128, 170)

# How many codes tall each drag-scroll strip is.
SCROLL_ZONE_CODES = 2
# Drag-scroll speed, in codes per second, from the strip's inner edge to the
# view's edge: the deeper the cursor, the faster the list moves.
SCROLL_SPEED_CODES_PER_SECOND = (3, 25)
SCROLL_TICK_MS = 16


class CodeTreeWidget(QTreeWidget):
    """A QTreeWidget that reports reparenting after an internal drag-drop.

    While a code is being dragged, the strips at the top and bottom of the
    view where dragging scrolls the list are two codes tall and shaded with a
    grey gradient, so it's visible where scrolling starts. A strip whose end of the
    list is already in view is left unshaded: nothing scrolls there, and the
    code under it is an ordinary drop target like any other.

    After each scroll step the drag is re-evaluated at the cursor, since the
    rows have moved under it even if the mouse hasn't — that's what keeps the
    drop indicator on the code under the cursor, including the first or last
    code once scrolling stops at an end.
    """

    codeReparented = Signal(int, object)  # (code_id, new_parent_code_id_or_None)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self._dragging = False
        self._last_drag_move = None
        self._zone_height = 0
        # Qt's own drag auto-scroll jumps a whole row per 150ms tick, restarts
        # (and so loses its acceleration) on every drag-move event, and blanks
        # the drop indicator after each jump; together that read as jitter.
        # This class scrolls the drag itself instead, a few pixels a frame.
        self.setAutoScroll(False)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self._scroll_timer = QTimer(self)
        self._scroll_timer.setInterval(SCROLL_TICK_MS)
        self._scroll_timer.timeout.connect(self._scroll_step)
        self._scroll_clock = QElapsedTimer()
        self._scroll_remainder = 0.0
        # Scrolling moves the viewport's pixels, gradient included, so the
        # strips have to be repainted after every step.
        self.verticalScrollBar().valueChanged.connect(self._on_scrolled)

    def code_row_height(self) -> int:
        first = self.topLevelItem(0)
        if first is not None:
            height = self.visualItemRect(first).height()
            if height > 0:
                return height
        return self.fontMetrics().height()

    def scroll_zone_height(self) -> int:
        return self._zone_height

    def scroll_velocity(self, y: float) -> float:
        """Drag-scroll speed in pixels per second for a cursor at viewport y.

        Negative scrolls up. Zero outside the strips and in a strip whose end
        of the list is already in view.
        """
        shade_top, shade_bottom = self.scroll_zone_shading()
        zone = self._zone_height
        if zone <= 0:
            return 0.0
        rect = self.viewport().rect()
        if shade_top and y < rect.top() + zone:
            depth, direction = (rect.top() + zone - y) / zone, -1
        elif shade_bottom and y > rect.bottom() + 1 - zone:
            depth, direction = (y - (rect.bottom() + 1 - zone)) / zone, 1
        else:
            return 0.0
        slow, fast = SCROLL_SPEED_CODES_PER_SECOND
        speed = slow + (fast - slow) * min(max(depth, 0.0), 1.0)
        return direction * speed * self.code_row_height()

    def scroll_zone_shading(self) -> tuple[bool, bool]:
        """Whether the (top, bottom) scroll strips are shaded right now."""
        if not self._dragging:
            return False, False
        bar = self.verticalScrollBar()
        return bar.value() > bar.minimum(), bar.value() < bar.maximum()

    def startDrag(self, supported_actions) -> None:
        # QDrag.exec blocks until the drag ends, however it ends (a drop
        # anywhere, Escape), so this is the one place sure to see it finish.
        self._begin_drag()
        try:
            super().startDrag(supported_actions)
        finally:
            self._end_drag()

    def dragEnterEvent(self, event) -> None:
        self._begin_drag()
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        self._last_drag_move = (
            event.mimeData(),
            event.possibleActions(),
            event.buttons(),
            event.modifiers(),
        )
        super().dragMoveEvent(event)
        # Started, never restarted: the platform sends move events even for a
        # hand held still, and restarting on each one is what made Qt's own
        # auto-scroll stutter.
        if not self._scroll_timer.isActive() and self.scroll_velocity(event.position().y()):
            self._scroll_remainder = 0.0
            self._scroll_clock.start()
            self._scroll_timer.start()

    def dragLeaveEvent(self, event) -> None:
        super().dragLeaveEvent(event)
        self._end_drag()

    def dropEvent(self, event) -> None:
        self._end_drag()
        selected = self.selectedItems()
        dragged_item = selected[0] if selected else self.currentItem()

        super().dropEvent(event)

        if dragged_item is None:
            return
        code_id = dragged_item.data(0, Qt.UserRole)
        parent_item = dragged_item.parent()
        new_parent_id = parent_item.data(0, Qt.UserRole) if parent_item is not None else None
        self.codeReparented.emit(code_id, new_parent_id)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        shade_top, shade_bottom = self.scroll_zone_shading()
        if not (shade_top or shade_bottom):
            return
        height = self._zone_height
        rect = self.viewport().rect()
        clear = QColor(SCROLL_ZONE_SHADE)
        clear.setAlpha(0)
        painter = QPainter(self.viewport())
        if shade_top:
            gradient = QLinearGradient(QPointF(0, rect.top()), QPointF(0, rect.top() + height))
            gradient.setColorAt(0, SCROLL_ZONE_SHADE)
            gradient.setColorAt(1, clear)
            painter.fillRect(rect.left(), rect.top(), rect.width(), height, gradient)
        if shade_bottom:
            top = rect.bottom() + 1 - height
            gradient = QLinearGradient(QPointF(0, rect.bottom() + 1), QPointF(0, top))
            gradient.setColorAt(0, SCROLL_ZONE_SHADE)
            gradient.setColorAt(1, clear)
            painter.fillRect(rect.left(), top, rect.width(), height, gradient)
        painter.end()

    def _begin_drag(self) -> None:
        # Measured per drag rather than once, since the font scale (and so the
        # row height) can change while the window is open.
        self._zone_height = SCROLL_ZONE_CODES * self.code_row_height()
        self._dragging = True
        self.viewport().update()

    def _end_drag(self) -> None:
        self._last_drag_move = None
        self._scroll_timer.stop()
        if self._dragging:
            self._dragging = False
            self.viewport().update()

    def _on_scrolled(self, _value) -> None:
        if self._dragging:
            self.viewport().update()

    def _scroll_step(self) -> None:
        position = self.viewport().mapFromGlobal(QCursor.pos())
        velocity = self.scroll_velocity(position.y()) if self._dragging else 0.0
        if velocity == 0.0:
            self._scroll_timer.stop()
            return
        # Paced by the clock rather than by ticks, so a late tick (a busy
        # repaint) catches up instead of slowing the scroll down.
        elapsed = min(self._scroll_clock.restart(), 100) / 1000
        self._scroll_remainder += velocity * elapsed
        pixels = int(self._scroll_remainder)
        if not pixels:
            return
        self._scroll_remainder -= pixels
        bar = self.verticalScrollBar()
        bar.setValue(bar.value() + pixels)
        # The rows just moved under a cursor that may not have, so the drop
        # indicator is re-aimed at whatever code is under it now.
        self._refresh_drop_target()

    def _refresh_drop_target(self) -> None:
        if not self._dragging or self._last_drag_move is None:
            return
        mime, actions, buttons, modifiers = self._last_drag_move
        position = self.viewport().mapFromGlobal(QCursor.pos())
        if not self.viewport().rect().contains(position):
            return
        self.dragMoveEvent(QDragMoveEvent(position, actions, mime, buttons, modifiers))
