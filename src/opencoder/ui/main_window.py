from __future__ import annotations

import sqlite3
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QFileDialog,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QSplitter,
)

from opencoder import db

PROJECT_FILTER = "OpenCoder Project (*.sqlite)"
TEXT_FILTER = "Text Files (*.txt);;All Files (*)"


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.conn: sqlite3.Connection | None = None
        self.project_path: Path | None = None

        self.setWindowTitle("OpenCoder")
        self.resize(900, 600)

        self.document_list = QListWidget()
        self.document_list.currentItemChanged.connect(self._on_document_selected)

        self.viewer = QPlainTextEdit()
        self.viewer.setReadOnly(True)

        splitter = QSplitter()
        splitter.addWidget(self.document_list)
        splitter.addWidget(self.viewer)
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
            self.viewer.clear()
            return
        doc_id = current.data(Qt.UserRole)
        doc = db.get_document(self.conn, doc_id)
        self.viewer.setPlainText(doc.content if doc else "")

    # -- Testable logic, independent of QFileDialog ------------------------

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

    def _set_connection(self, conn: sqlite3.Connection, path: Path) -> None:
        if self.conn is not None:
            self.conn.close()
        self.conn = conn
        self.project_path = path
        self.setWindowTitle(f"OpenCoder — {path.name}")
        self.statusBar().showMessage(str(path))
        self._refresh_documents()
        self._update_actions_enabled()

    def _refresh_documents(self) -> None:
        self.document_list.clear()
        if self.conn is None:
            return
        for doc in db.list_documents(self.conn):
            item = QListWidgetItem(doc.name)
            item.setData(Qt.UserRole, doc.id)
            self.document_list.addItem(item)

    def _select_document(self, document_id: int) -> None:
        for row in range(self.document_list.count()):
            item = self.document_list.item(row)
            if item.data(Qt.UserRole) == document_id:
                self.document_list.setCurrentItem(item)
                return

    def _update_actions_enabled(self) -> None:
        self.import_action.setEnabled(self.conn is not None)
