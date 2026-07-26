from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLineEdit


class CodeFilterLineEdit(QLineEdit):
    """A QLineEdit whose Up/Down keys cycle the matched code instead of moving the cursor."""

    cyclePressed = Signal(int)  # +1 for down/next, -1 for up/previous
    escapePressed = Signal()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Down:
            self.cyclePressed.emit(1)
            return
        if event.key() == Qt.Key_Up:
            self.cyclePressed.emit(-1)
            return
        if event.key() == Qt.Key_Escape:
            self.escapePressed.emit()
            return
        super().keyPressEvent(event)
