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
            ("Esc", "Return focus to the text pane (from any other pane)"),
        ],
    ),
    (
        "Text pane",
        [
            ("Up / Down", "Cycle the matched/highlighted code (with a selection)"),
            ("Enter", "Apply the current code to the selection"),
            ("x", "Delete segment(s) at the cursor, or in the visual selection"),
            ("Right-click", "Show the standard menu, plus \"Delete Segment\" over a coded span"),
            ("c", "Jump to the next coded segment (selected users only)"),
            ("C", "Jump to the previous coded segment (selected users only)"),
            ("h j k l", "Move left / down / up / right (arrow keys also work)"),
            ("w / b / e", "Move to next / previous / end of word"),
            ("W / B / E", "Move by WORD (whitespace-delimited)"),
            ("0 / $", "Move to start / end of line"),
            ("gg / G", "Jump to top / bottom of document"),
            ("H / L / M", "Jump to first / last / middle visible line in viewport"),
            ("zz", "Center the viewport on the current cursor line"),
            ("f<char> / F<char>", "Jump forward / backward to next occurrence of char in document"),
            ("v", "Toggle visual (selection) mode"),
            ("i", "Enter insert (text editing) mode"),
            ("/", "Enter search mode (regex, smartcase)"),
            ("n / N", "Repeat last search forward / backward"),
            ("?", "Show this shortcuts popup"),
            ("Esc", "Exit visual/search/insert mode, or close this popup"),
        ],
    ),
    (
        "Insert mode",
        [
            ("Esc", "Return to normal mode"),
            ("(button)", "The Insert Mode button below the text pane also toggles it"),
        ],
    ),
    (
        "Code filter",
        [
            ("Up / Down", "Cycle matched codes, including \"(add new code)\" when shown"),
            ("Enter", "Apply the matched code, or create a new code"),
        ],
    ),
    (
        "Codebook",
        [
            ("Double-click a code", "Apply it to the text pane's current selection"),
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
