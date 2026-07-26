from __future__ import annotations

import sqlite3
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QColor, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from opencoder import db
from opencoder.db import Code

PROJECT_FILTER = "OpenCoder Project (*.sqlite)"
TEXT_FILTER = "Text Files (*.txt);;All Files (*)"

CODE_COLOR_PALETTE = [
    "#f94144",
    "#f3722c",
    "#f9c74f",
    "#90be6d",
    "#43aa8b",
    "#577590",
    "#277da1",
    "#9c6ade",
]

HIGHLIGHT_ALPHA = 120


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.conn: sqlite3.Connection | None = None
        self.project_path: Path | None = None
        self._current_document_id: int | None = None

        self.setWindowTitle("OpenCoder")
        self.resize(1100, 650)

        self.document_list = QListWidget()
        self.document_list.currentItemChanged.connect(self._on_document_selected)

        self.viewer = QPlainTextEdit()
        self.viewer.setReadOnly(True)

        self.code_list = QListWidget()

        self.new_code_button = QPushButton("New Code…")
        self.new_code_button.clicked.connect(self._on_new_code)

        self.apply_code_button = QPushButton("Apply to Selection")
        self.apply_code_button.clicked.connect(self._on_apply_code)

        code_panel = QWidget()
        code_layout = QVBoxLayout(code_panel)
        code_layout.addWidget(self.code_list)
        button_row = QHBoxLayout()
        button_row.addWidget(self.new_code_button)
        button_row.addWidget(self.apply_code_button)
        code_layout.addLayout(button_row)

        splitter = QSplitter()
        splitter.addWidget(self.document_list)
        splitter.addWidget(self.viewer)
        splitter.addWidget(code_panel)
        splitter.setStretchFactor(1, 1)
        self.setCentralWidget(splitter)

        self._build_menu()
        self._update_actions_enabled()
        self.statusBar().showMessage("No project open")

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&File")

        new_action = QAction("&New Project…", self)
        new_action.triggered.connect(self._on_new_project)
        file_menu.addAction(new_action)

        open_action = QAction("&Open Project…", self)
        open_action.triggered.connect(self._on_open_project)
        file_menu.addAction(open_action)

        file_menu.addSeparator()

        self.import_action = QAction("&Import Document…", self)
        self.import_action.triggered.connect(self._on_import_document)
        file_menu.addAction(self.import_action)

        file_menu.addSeparator()

        quit_action = QAction("&Quit", self)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

    # -- Dialog-triggering slots -------------------------------------------

    def _on_new_project(self) -> None:
        path_str, _ = QFileDialog.getSaveFileName(self, "New Project", "", PROJECT_FILTER)
        if not path_str:
            return
        if not path_str.endswith(".sqlite"):
            path_str += ".sqlite"
        self.create_project(Path(path_str))

    def _on_open_project(self) -> None:
        path_str, _ = QFileDialog.getOpenFileName(self, "Open Project", "", PROJECT_FILTER)
        if not path_str:
            return
        self.open_project(Path(path_str))

    def _on_import_document(self) -> None:
        path_str, _ = QFileDialog.getOpenFileName(self, "Import Document", "", TEXT_FILTER)
        if not path_str:
            return
        self.import_document(Path(path_str))

    def _on_document_selected(
        self, current: QListWidgetItem | None, _previous: QListWidgetItem | None
    ) -> None:
        if current is None or self.conn is None:
            self._current_document_id = None
            self.viewer.clear()
            self.viewer.setExtraSelections([])
            return
        doc_id = current.data(Qt.UserRole)
        doc = db.get_document(self.conn, doc_id)
        self._current_document_id = doc_id
        self.viewer.setPlainText(doc.content if doc else "")
        self._refresh_highlights()

    def _on_new_code(self) -> None:
        if self.conn is None:
            return
        name, ok = QInputDialog.getText(self, "New Code", "Code name:")
        if not ok or not name.strip():
            return
        self.add_code(name.strip())

    def _on_apply_code(self) -> None:
        if self._current_document_id is None:
            QMessageBox.information(self, "No Document", "Open a document first.")
            return
        cursor = self.viewer.textCursor()
        if not cursor.hasSelection():
            QMessageBox.information(self, "No Selection", "Select some text in the document first.")
            return
        code_item = self.code_list.currentItem()
        if code_item is None:
            QMessageBox.information(self, "No Code Selected", "Select a code to apply first.")
            return
        self.apply_segment(code_item.data(Qt.UserRole), cursor.selectionStart(), cursor.selectionEnd())

    # -- Testable logic, independent of QFileDialog / QMessageBox ---------

    def create_project(self, path: Path) -> None:
        if path.exists():
            path.unlink()
        self._set_connection(db.connect(path), path)

    def open_project(self, path: Path) -> None:
        self._set_connection(db.connect(path), path)

    def import_document(self, path: Path) -> None:
        if self.conn is None:
            return
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            QMessageBox.warning(
                self, "Import Failed", f"Could not read {path.name} as UTF-8 text."
            )
            return
        doc = db.create_document(self.conn, path.name, content)
        self._refresh_documents()
        self._select_document(doc.id)

    def add_code(self, name: str, color: str | None = None) -> Code:
        if self.conn is None:
            raise RuntimeError("No project open")
        if color is None:
            color = self._next_color()
        code = db.create_code(self.conn, name, color=color)
        self._refresh_codes()
        return code

    def apply_segment(self, code_id: int, start: int, end: int) -> None:
        if self.conn is None or self._current_document_id is None:
            return
        db.create_segment(self.conn, self._current_document_id, code_id, start, end)
        self._refresh_highlights()

    def _set_connection(self, conn: sqlite3.Connection, path: Path) -> None:
        if self.conn is not None:
            self.conn.close()
        self.conn = conn
        self.project_path = path
        self._current_document_id = None
        self.setWindowTitle(f"OpenCoder — {path.name}")
        self.statusBar().showMessage(str(path))
        self._refresh_documents()
        self._refresh_codes()
        self._update_actions_enabled()

    def _refresh_documents(self) -> None:
        self.document_list.clear()
        if self.conn is None:
            return
        for doc in db.list_documents(self.conn):
            item = QListWidgetItem(doc.name)
            item.setData(Qt.UserRole, doc.id)
            self.document_list.addItem(item)

    def _refresh_codes(self) -> None:
        self.code_list.clear()
        if self.conn is None:
            return
        for code in db.list_codes(self.conn):
            item = QListWidgetItem(code.name)
            item.setData(Qt.UserRole, code.id)
            if code.color:
                item.setBackground(QColor(code.color))
            self.code_list.addItem(item)

    def _refresh_highlights(self) -> None:
        if self.conn is None or self._current_document_id is None:
            self.viewer.setExtraSelections([])
            return
        codes_by_id = {code.id: code for code in db.list_codes(self.conn)}
        segments = db.list_segments_for_document(self.conn, self._current_document_id)

        selections = []
        for segment in segments:
            code = codes_by_id.get(segment.code_id)
            color = QColor(code.color if code and code.color else "#ffff00")
            color.setAlpha(HIGHLIGHT_ALPHA)

            cursor = QTextCursor(self.viewer.document())
            cursor.setPosition(segment.start_offset)
            cursor.setPosition(segment.end_offset, QTextCursor.KeepAnchor)

            fmt = QTextCharFormat()
            fmt.setBackground(color)

            selection = QTextEdit.ExtraSelection()
            selection.cursor = cursor
            selection.format = fmt
            selections.append(selection)

        self.viewer.setExtraSelections(selections)

    def _select_document(self, document_id: int) -> None:
        for row in range(self.document_list.count()):
            item = self.document_list.item(row)
            if item.data(Qt.UserRole) == document_id:
                self.document_list.setCurrentItem(item)
                return

    def _next_color(self) -> str:
        count = len(db.list_codes(self.conn)) if self.conn else 0
        return CODE_COLOR_PALETTE[count % len(CODE_COLOR_PALETTE)]

    def _update_actions_enabled(self) -> None:
        self.import_action.setEnabled(self.conn is not None)
