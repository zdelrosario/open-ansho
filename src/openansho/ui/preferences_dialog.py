from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QVBoxLayout,
)


class PreferencesDialog(QDialog):
    darkModeToggled = Signal(bool)

    def __init__(self, dark_mode: bool, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Preferences")

        layout = QVBoxLayout(self)

        self.dark_mode_checkbox = QCheckBox("Dark mode")
        self.dark_mode_checkbox.setChecked(dark_mode)
        self.dark_mode_checkbox.toggled.connect(self.darkModeToggled)
        layout.addWidget(self.dark_mode_checkbox)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)
