from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLineEdit


class CodeFilterLineEdit(QLineEdit):
    """A QLineEdit whose Up/Down keys cycle the matched code instead of moving the cursor.

    Ctrl+K / Ctrl+J are vim-flavored aliases for Up / Down. On macOS Qt
    reports Cmd as ControlModifier and the Control key as MetaModifier;
    either one counts, so the physical Control key works there too.
    """

    cyclePressed = Signal(int)  # +1 for down/next, -1 for up/previous

    def keyPressEvent(self, event) -> None:
        key = event.key()
        control = bool(event.modifiers() & (Qt.ControlModifier | Qt.MetaModifier))
        if key == Qt.Key_Down or (control and key == Qt.Key_J):
            self.cyclePressed.emit(1)
            return
        if key == Qt.Key_Up or (control and key == Qt.Key_K):
            self.cyclePressed.emit(-1)
            return
        super().keyPressEvent(event)
