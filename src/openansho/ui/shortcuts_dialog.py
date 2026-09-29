from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

SHORTCUT_SECTIONS = [
    (
        "Anywhere",
        [
            ("Space", "Jump focus to the code filter"),
            ("Esc", "Return focus to the text pane (from any other pane)"),
            ("Ctrl++", "Increase the application font size by 25%"),
            ("Ctrl+-", "Decrease the application font size by 25%"),
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
            ("zt", "Scroll the viewport so the current cursor line is at the top"),
            ("zb", "Scroll the viewport so the current cursor line is at the bottom"),
            ("Ctrl+E / Ctrl+Y", "Scroll the viewport down / up by one line"),
            ("f<char> / F<char>", "Jump forward / backward to next occurrence of char in document"),
            ("v", "Toggle visual (selection) mode"),
            ("V", "Enter visual mode with the entire current line selected"),
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
        "PDF page pane",
        [
            ("Drag", "Draw a rectangular region on the page and select it for coding"),
            ("Click a region", "Select it in the text pane, ready for a code"),
            ("Right-click a region", "Remove one of its codes, or delete the region"),
            ("‹ / ›", "Turn to the previous / next page"),
            (
                "▭",
                "Each region's marker in the text pane — one character, so the "
                "vim motions and coding shortcuts treat it like any other",
            ),
        ],
    ),
    (
        "Codebook",
        [
            ("Double-click a code", "Apply it to the text pane's current selection"),
            (
                "Right-click",
                "New child code, rename, edit description, \"Move to Top Level\", "
                "assign base color, merge, delete",
            ),
        ],
    ),
]


class ShortcutsDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Keyboard Shortcuts")
        self.resize(520, 560)

        # The sections scroll rather than sizing the dialog to all of them:
        # laid out in full they are taller than a 1080p screen, and the list
        # only grows as shortcuts are added.
        content = QWidget()
        content_layout = QVBoxLayout(content)

        for title, shortcuts in SHORTCUT_SECTIONS:
            heading = QLabel(f"<b>{title}</b>")
            content_layout.addWidget(heading)
            for keys, description in shortcuts:
                row = QLabel(f"<tt>{keys}</tt> — {description}")
                row.setTextFormat(Qt.RichText)
                row.setWordWrap(True)
                content_layout.addWidget(row)
            content_layout.addSpacing(8)

        scroll = QScrollArea()
        scroll.setWidget(content)
        scroll.setWidgetResizable(True)

        layout = QVBoxLayout(self)
        layout.addWidget(scroll, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
