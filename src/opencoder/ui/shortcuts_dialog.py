from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
)

SHORTCUT_SECTIONS = [
    (
        "Anywhere",
        [
            ("Space", "Jump focus to the code filter"),
            ("?", "Show this shortcuts popup"),
        ],
    ),
    (
        "Text pane",
        [
            ("Up / Down", "Cycle the matched/highlighted code (with a selection)"),
            ("Enter", "Apply the current code to the selection"),
            ("x", "Delete segment(s) at the cursor, or in the visual selection"),
            ("c", "Jump to the next coded segment"),
            ("p", "Jump to the previous coded segment"),
            ("h j k l", "Move left / down / up / right"),
            ("w / b / e", "Move to next / previous / end of word"),
            ("W / B / E", "Move by WORD (whitespace-delimited)"),
            ("0 / $", "Move to start / end of line"),
            ("gg / G", "Jump to top / bottom of document"),
            ("H / L", "Jump to first / last visible line in viewport"),
            ("v", "Toggle visual (selection) mode"),
            ("/", "Enter search mode (regex, smartcase)"),
            ("n / N", "Repeat last search forward / backward"),
            ("Esc", "Exit visual/search mode, or close this popup"),
        ],
    ),
    (
        "Code filter",
        [
            ("Up / Down", "Cycle matched codes"),
            ("Enter", "Apply the matched code, or create a new code"),
            ("Esc", "Return focus to the text pane"),
        ],
    ),
]


class ShortcutsDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Keyboard Shortcuts")
        self.resize(420, 480)

        layout = QVBoxLayout(self)

        for title, shortcuts in SHORTCUT_SECTIONS:
            heading = QLabel(f"<b>{title}</b>")
            layout.addWidget(heading)
            for keys, description in shortcuts:
                row = QLabel(f"<tt>{keys}</tt> — {description}")
                row.setTextFormat(Qt.RichText)
                layout.addWidget(row)
            layout.addSpacing(8)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
