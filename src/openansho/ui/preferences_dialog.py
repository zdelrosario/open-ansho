from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from openansho.ui.font_scale import (
    FONT_SCALE_STEP_PERCENT,
    MAX_FONT_SCALE_PERCENT,
    MIN_FONT_SCALE_PERCENT,
)


class PreferencesDialog(QDialog):
    darkModeToggled = Signal(bool)
    fontScaleChanged = Signal(int)
    changeUsernameRequested = Signal()

    def __init__(self, dark_mode: bool, font_scale_percent: int, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Preferences")

        layout = QVBoxLayout(self)

        self.dark_mode_checkbox = QCheckBox("Dark mode")
        self.dark_mode_checkbox.setChecked(dark_mode)
        self.dark_mode_checkbox.toggled.connect(self.darkModeToggled)
        layout.addWidget(self.dark_mode_checkbox)

        font_scale_row = QHBoxLayout()
        font_scale_row.addWidget(QLabel("Font size:"))
        self.font_scale_spinbox = QSpinBox()
        self.font_scale_spinbox.setRange(MIN_FONT_SCALE_PERCENT, MAX_FONT_SCALE_PERCENT)
        self.font_scale_spinbox.setSingleStep(FONT_SCALE_STEP_PERCENT)
        self.font_scale_spinbox.setSuffix(" %")
        self.font_scale_spinbox.setValue(font_scale_percent)
        self.font_scale_spinbox.valueChanged.connect(self.fontScaleChanged)
        font_scale_row.addWidget(self.font_scale_spinbox)
        font_scale_row.addStretch()
        layout.addLayout(font_scale_row)

        self.change_username_button = QPushButton("Change Username…")
        self.change_username_button.clicked.connect(self.changeUsernameRequested)
        layout.addWidget(self.change_username_button)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)
