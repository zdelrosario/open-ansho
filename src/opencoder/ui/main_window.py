from __future__ import annotations

import sqlite3
from pathlib import Path

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QAction, QColor, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from opencoder import db, reporting
from opencoder.db import Code
from opencoder.ui.code_filter_input import CodeFilterLineEdit
from opencoder.ui.code_tree import CodeTreeWidget
from opencoder.ui.report_dialog import CodeFrequencyDialog

PROJECT_FILTER = "OpenCoder Project (*.sqlite)"
TEXT_FILTER = "Text Files (*.txt);;All Files (*)"
CSV_FILTER = "CSV Files (*.csv)"
JSON_FILTER = "JSON Files (*.json)"

PROJECT_SECTION_LABEL_OPEN = "Project"
PROJECT_SECTION_LABEL_CLOSED = "Project (first open a project)"

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

SNIPPET_MAX_LENGTH = 60


def _apply_filter_to_item(item: QTreeWidgetItem, query: str) -> bool:
    """Hide items that don't match `query` and have no matching descendant.

    Returns whether `item` (or any descendant) matches, so callers can
    keep an ancestor visible whenever one of its children matches.
    """
    self_match = not query or query in item.text(0).lower()
    child_match = False
    for row in range(item.childCount()):
        if _apply_filter_to_item(item.child(row), query):
            child_match = True

    visible = self_match or child_match
    item.setHidden(not visible)
    if query and child_match:
        item.setExpanded(True)
    return visible


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.conn: sqlite3.Connection | None = None
        self.project_path: Path | None = None
        self._current_document_id: int | None = None

        self.setWindowTitle("OpenCoder")
        self.resize(1150, 650)

        self.document_list = QListWidget()
        self.document_list.currentItemChanged.connect(self._on_document_selected)

        self.viewer = QPlainTextEdit()
        self.viewer.setReadOnly(True)
        self.viewer.selectionChanged.connect(self._on_viewer_selection_changed)

        self.code_tree = CodeTreeWidget()
        self.code_tree.setHeaderHidden(True)
        self.code_tree.currentItemChanged.connect(self._on_code_selected)
        self.code_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.code_tree.customContextMenuRequested.connect(self._on_code_context_menu)
        self.code_tree.codeReparented.connect(self._on_code_reparented)

        self._code_items_by_id: dict[int, QTreeWidgetItem] = {}

        self.code_filter_input = CodeFilterLineEdit()
        self.code_filter_input.setPlaceholderText("Filter codes, or type a new name and press Enter…")
        self.code_filter_input.textChanged.connect(self._on_code_filter_changed)
        self.code_filter_input.returnPressed.connect(self._on_code_filter_return_pressed)
        self.code_filter_input.cyclePressed.connect(self._on_code_filter_cycle)

        self.apply_code_button = QPushButton("Apply to Selection")
        self.apply_code_button.clicked.connect(self._on_apply_code)

        self.segment_list = QListWidget()
        self.segment_list.itemDoubleClicked.connect(self._on_segment_activated)

        code_panel = QWidget()
        code_layout = QVBoxLayout(code_panel)
        code_layout.setContentsMargins(0, 0, 0, 0)

        code_splitter = QSplitter(Qt.Vertical)

        tree_container = QWidget()
        tree_layout = QVBoxLayout(tree_container)
        tree_layout.setContentsMargins(0, 0, 0, 0)
        tree_layout.addWidget(QLabel("Codebook"))
        tree_layout.addWidget(self.code_filter_input)
        tree_layout.addWidget(self.code_tree)
        tree_layout.addWidget(self.apply_code_button)
        code_splitter.addWidget(tree_container)

        segments_container = QWidget()
        segments_layout = QVBoxLayout(segments_container)
        segments_layout.setContentsMargins(0, 0, 0, 0)
        segments_layout.addWidget(QLabel("Coded Segments"))
        segments_layout.addWidget(self.segment_list)
        code_splitter.addWidget(segments_container)

        code_layout.addWidget(code_splitter)

        splitter = QSplitter()
        splitter.addWidget(self.document_list)
        splitter.addWidget(self.viewer)
        splitter.addWidget(code_panel)
        splitter.setStretchFactor(1, 1)
        self.setCentralWidget(splitter)

        self._build_menu()
        self._update_actions_enabled()
        self.statusBar().showMessage("No project open")

        QApplication.instance().installEventFilter(self)

    def closeEvent(self, event) -> None:
        QApplication.instance().removeEventFilter(self)
        super().closeEvent(event)

    def eventFilter(self, watched, event) -> bool:
        if event.type() == QEvent.KeyPress:
            if event.key() == Qt.Key_Space:
                if QApplication.focusWidget() is not self.code_filter_input:
                    self.code_filter_input.setFocus()
                    return True
            elif event.key() in (Qt.Key_Up, Qt.Key_Down):
                if QApplication.focusWidget() is self.viewer and self.viewer.textCursor().hasSelection():
                    self._cycle_matched_code(-1 if event.key() == Qt.Key_Up else 1)
                    return True
        return super().eventFilter(watched, event)

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&File")

        # -- Project management -------------------------------------------
        new_action = QAction("&New Project…", self)
        new_action.triggered.connect(self._on_new_project)
        file_menu.addAction(new_action)

        open_action = QAction("&Open Project…", self)
        open_action.triggered.connect(self._on_open_project)
        file_menu.addAction(open_action)

        file_menu.addSeparator()

        # -- Project contents: import/export, require an open project -----
        self.project_section_action = QAction(PROJECT_SECTION_LABEL_CLOSED, self)
        self.project_section_action.setEnabled(False)
        file_menu.addAction(self.project_section_action)

        self.import_action = QAction("&Import Document…", self)
        self.import_action.triggered.connect(self._on_import_document)
        file_menu.addAction(self.import_action)

        self.export_csv_action = QAction("Export Segments (&CSV)…", self)
        self.export_csv_action.triggered.connect(self._on_export_csv)
        file_menu.addAction(self.export_csv_action)

        self.export_json_action = QAction("Export Segments (&JSON)…", self)
        self.export_json_action.triggered.connect(self._on_export_json)
        file_menu.addAction(self.export_json_action)

        file_menu.addSeparator()

        # -- Application ----------------------------------------------------
        quit_action = QAction("&Quit", self)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        view_menu = self.menuBar().addMenu("&View")

        self.code_frequency_action = QAction("&Code Frequency Report…", self)
        self.code_frequency_action.triggered.connect(self._on_code_frequency_report)
        view_menu.addAction(self.code_frequency_action)

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

    def _on_code_selected(
        self, _current: QTreeWidgetItem | None, _previous: QTreeWidgetItem | None
    ) -> None:
        self._refresh_segments_for_selected_code()

    def _on_code_reparented(self, code_id: int, new_parent_id: int | None) -> None:
        if self.conn is None:
            return
        try:
            self.reparent_code(code_id, new_parent_id)
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid Move", str(exc))
            self._refresh_codes()

    def _on_code_filter_changed(self, text: str) -> None:
        self._apply_code_filter(text)
        self._sync_matched_code_selection()

    def _on_code_filter_cycle(self, direction: int) -> None:
        self._cycle_matched_code(direction)

    def _on_code_filter_return_pressed(self) -> None:
        if self.conn is None:
            return
        text = self.code_filter_input.text().strip()
        if not text:
            return

        matches = self._matching_code_items(text)
        if matches:
            code_id = self._current_or_first_match_id(matches)
            cursor = self.viewer.textCursor()
            if cursor.hasSelection():
                self.apply_segment(code_id, cursor.selectionStart(), cursor.selectionEnd())
            else:
                self._select_code(code_id)
            return

        code = self.add_code(text)
        self.code_filter_input.clear()
        self._select_code(code.id)

    def _on_apply_code(self) -> None:
        if self._current_document_id is None:
            QMessageBox.information(self, "No Document", "Open a document first.")
            return
        cursor = self.viewer.textCursor()
        if not cursor.hasSelection():
            QMessageBox.information(self, "No Selection", "Select some text in the document first.")
            return
        code_item = self.code_tree.currentItem()
        if code_item is None:
            QMessageBox.information(self, "No Code Selected", "Select a code to apply first.")
            return
        self.apply_segment(
            code_item.data(0, Qt.UserRole), cursor.selectionStart(), cursor.selectionEnd()
        )

    def _on_code_context_menu(self, pos) -> None:
        if self.conn is None:
            return
        item = self.code_tree.itemAt(pos)
        if item is None:
            return

        menu = QMenu(self)
        new_child_action = menu.addAction("New Child Code…")
        rename_action = menu.addAction("Rename…")

        chosen = menu.exec(self.code_tree.viewport().mapToGlobal(pos))
        if chosen is None:
            return
        if chosen is new_child_action:
            self._on_new_child_code(item.data(0, Qt.UserRole))
        elif chosen is rename_action:
            self._on_rename_code(item.data(0, Qt.UserRole), item.text(0))

    def _on_new_child_code(self, parent_id: int) -> None:
        name, ok = QInputDialog.getText(self, "New Child Code", "Code name:")
        if not ok or not name.strip():
            return
        self.add_code(name.strip(), parent_id=parent_id)

    def _on_rename_code(self, code_id: int, current_name: str) -> None:
        name, ok = QInputDialog.getText(self, "Rename Code", "Code name:", text=current_name)
        if not ok or not name.strip():
            return
        self.rename_code(code_id, name.strip())

    def _on_segment_activated(self, item: QListWidgetItem) -> None:
        document_id, start, end = item.data(Qt.UserRole)
        self._select_document(document_id)
        cursor = self.viewer.textCursor()
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.KeepAnchor)
        self.viewer.setTextCursor(cursor)
        self.viewer.ensureCursorVisible()

    def _on_export_csv(self) -> None:
        if self.conn is None:
            return
        path_str, _ = QFileDialog.getSaveFileName(self, "Export Segments (CSV)", "", CSV_FILTER)
        if not path_str:
            return
        if not path_str.endswith(".csv"):
            path_str += ".csv"
        count = reporting.export_segments_csv(self.conn, path_str)
        QMessageBox.information(self, "Export Complete", f"Exported {count} segment(s).")

    def _on_export_json(self) -> None:
        if self.conn is None:
            return
        path_str, _ = QFileDialog.getSaveFileName(self, "Export Segments (JSON)", "", JSON_FILTER)
        if not path_str:
            return
        if not path_str.endswith(".json"):
            path_str += ".json"
        count = reporting.export_segments_json(self.conn, path_str)
        QMessageBox.information(self, "Export Complete", f"Exported {count} segment(s).")

    def _on_code_frequency_report(self) -> None:
        if self.conn is None:
            return
        rows = reporting.code_frequency(self.conn)
        dialog = CodeFrequencyDialog(rows, self)
        dialog.exec()

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

    def add_code(self, name: str, parent_id: int | None = None, color: str | None = None) -> Code:
        if self.conn is None:
            raise RuntimeError("No project open")
        if color is None:
            color = self._next_color()
        code = db.create_code(self.conn, name, parent_id=parent_id, color=color)
        self._refresh_codes()
        return code

    def rename_code(self, code_id: int, name: str) -> Code:
        if self.conn is None:
            raise RuntimeError("No project open")
        code = db.rename_code(self.conn, code_id, name)
        self._refresh_codes()
        return code

    def reparent_code(self, code_id: int, parent_id: int | None) -> Code:
        if self.conn is None:
            raise RuntimeError("No project open")
        if parent_id == code_id:
            raise ValueError("A code cannot be its own parent.")
        if parent_id is not None and self._is_descendant_of(parent_id, code_id):
            raise ValueError("Cannot move a code under one of its own descendants.")
        code = db.set_code_parent(self.conn, code_id, parent_id)
        self._refresh_codes()
        return code

    def _is_descendant_of(self, candidate_id: int, ancestor_id: int) -> bool:
        if self.conn is None:
            return False
        codes_by_id = {code.id: code for code in db.list_codes(self.conn)}
        current = codes_by_id.get(candidate_id)
        while current is not None and current.parent_id is not None:
            if current.parent_id == ancestor_id:
                return True
            current = codes_by_id.get(current.parent_id)
        return False

    def apply_segment(self, code_id: int, start: int, end: int) -> None:
        if self.conn is None or self._current_document_id is None:
            return
        db.create_segment(self.conn, self._current_document_id, code_id, start, end)
        self._refresh_highlights()
        self._refresh_segments_for_selected_code()

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
        self.code_tree.clear()
        self.segment_list.clear()
        self._code_items_by_id = {}
        if self.conn is None:
            return

        codes = db.list_codes(self.conn)
        for code in codes:
            item = QTreeWidgetItem([code.name])
            item.setData(0, Qt.UserRole, code.id)
            if code.color:
                item.setBackground(0, QColor(code.color))
            self._code_items_by_id[code.id] = item

        for code in codes:
            item = self._code_items_by_id[code.id]
            parent_item = self._code_items_by_id.get(code.parent_id) if code.parent_id else None
            if parent_item is not None:
                parent_item.addChild(item)
            else:
                self.code_tree.addTopLevelItem(item)

        self.code_tree.expandAll()
        self._apply_code_filter(self.code_filter_input.text())
        self._sync_matched_code_selection()

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

    def _refresh_segments_for_selected_code(self) -> None:
        self.segment_list.clear()
        if self.conn is None:
            return
        item = self.code_tree.currentItem()
        if item is None:
            return
        code_id = item.data(0, Qt.UserRole)

        documents_by_id = {doc.id: doc for doc in db.list_documents(self.conn)}
        for segment in db.list_segments_for_code(self.conn, code_id):
            doc = documents_by_id.get(segment.document_id)
            doc_name = doc.name if doc else "?"
            snippet = doc.content[segment.start_offset : segment.end_offset] if doc else ""
            if len(snippet) > SNIPPET_MAX_LENGTH:
                snippet = snippet[:SNIPPET_MAX_LENGTH] + "…"

            list_item = QListWidgetItem(f"{doc_name}: “{snippet}”")
            list_item.setData(
                Qt.UserRole, (segment.document_id, segment.start_offset, segment.end_offset)
            )
            self.segment_list.addItem(list_item)

    def _apply_code_filter(self, text: str) -> None:
        query = text.strip().lower()
        for row in range(self.code_tree.topLevelItemCount()):
            _apply_filter_to_item(self.code_tree.topLevelItem(row), query)

    def _matching_code_items(self, text: str) -> list[QTreeWidgetItem]:
        """Codes matching `text`; an empty/blank query matches every code."""
        query = text.strip().lower()

        matches: list[QTreeWidgetItem] = []

        def walk(item: QTreeWidgetItem) -> None:
            if not query or query in item.text(0).lower():
                matches.append(item)
            for row in range(item.childCount()):
                walk(item.child(row))

        for row in range(self.code_tree.topLevelItemCount()):
            walk(self.code_tree.topLevelItem(row))
        return matches

    def _current_or_first_match_id(self, matches: list[QTreeWidgetItem]) -> int:
        current = self.code_tree.currentItem()
        if current in matches:
            return current.data(0, Qt.UserRole)
        return matches[0].data(0, Qt.UserRole)

    def _sync_matched_code_selection(self) -> None:
        text = self.code_filter_input.text().strip()
        if not text:
            return
        matches = self._matching_code_items(text)
        if not matches:
            self.code_tree.setCurrentItem(None)
            return
        current = self.code_tree.currentItem()
        if current in matches:
            return
        self.code_tree.setCurrentItem(matches[0])

    def _cycle_matched_code(self, direction: int) -> None:
        matches = self._matching_code_items(self.code_filter_input.text())
        if not matches:
            return
        current = self.code_tree.currentItem()
        index = (matches.index(current) + direction) % len(matches) if current in matches else 0
        self.code_tree.setCurrentItem(matches[index])

    def _ensure_code_selected(self) -> None:
        """Guarantee some code is selected, without disturbing an existing selection."""
        if self.code_tree.currentItem() is not None:
            return
        matches = self._matching_code_items(self.code_filter_input.text())
        if matches:
            self.code_tree.setCurrentItem(matches[0])

    def _on_viewer_selection_changed(self) -> None:
        if self.viewer.textCursor().hasSelection():
            self._ensure_code_selected()
        else:
            self.code_tree.setCurrentItem(None)

    def _select_code(self, code_id: int) -> None:
        item = self._code_items_by_id.get(code_id)
        if item is not None:
            self.code_tree.setCurrentItem(item)

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
        has_project = self.conn is not None
        self.import_action.setEnabled(has_project)
        self.export_csv_action.setEnabled(has_project)
        self.export_json_action.setEnabled(has_project)
        self.code_frequency_action.setEnabled(has_project)
        self.project_section_action.setText(
            PROJECT_SECTION_LABEL_OPEN if has_project else PROJECT_SECTION_LABEL_CLOSED
        )
