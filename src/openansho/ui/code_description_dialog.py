from __future__ import annotations

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QTextOption
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
)


class CodeDescriptionDialog(QDialog):
    """Multi-line editor for a code's description; Ctrl+Enter accepts it."""

    def __init__(self, current_description: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Description")

        self.editor = QPlainTextEdit()
        self.editor.setPlainText(current_description)
        self.editor.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self.editor.setWordWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        self.editor.installEventFilter(self)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        hint = QLabel("Press Ctrl+Enter to save (same as OK).")
        hint.setEnabled(False)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Code description:"))
        layout.addWidget(self.editor)
        layout.addWidget(buttons)
        layout.addWidget(hint)

        self.resize(480, 300)
        self.editor.setFocus()

    def description(self) -> str:
        return self.editor.toPlainText()

    def eventFilter(self, watched, event) -> bool:
        # Plain Enter has to keep inserting newlines, so only Ctrl+Enter accepts.
        # On macOS Qt reports Cmd as ControlModifier and the Control key as
        # MetaModifier; either one counts, so the physical Control key works too.
        if (
            watched is self.editor
            and event.type() == QEvent.KeyPress
            and event.key() in (Qt.Key_Return, Qt.Key_Enter)
            and event.modifiers() & (Qt.ControlModifier | Qt.MetaModifier)
        ):
            self.accept()
            return True
        return super().eventFilter(watched, event)
