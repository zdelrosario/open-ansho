from __future__ import annotations

import html
import random
import sqlite3
from pathlib import Path

from PySide6.QtCore import QEvent, QSettings, Qt
from PySide6.QtGui import QAction, QColor, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QHeaderView,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from opencoder import db, reporting, user
from opencoder.db import Code
from opencoder.ui.code_filter_input import CodeFilterLineEdit
from opencoder.ui.code_tree import CodeTreeWidget
from opencoder.ui.report_dialog import CodeFrequencyDialog, CodeUserFrequencyDialog
from opencoder.ui.shortcuts_dialog import ShortcutsDialog
from opencoder.ui.vim_viewer import VimTextViewer

PROJECT_FILTER = "OpenCoder Project (*.sqlite)"
TEXT_FILTER = "Text Files (*.txt);;All Files (*)"
CSV_FILTER = "CSV Files (*.csv)"
JSON_FILTER = "JSON Files (*.json)"

PROJECT_SECTION_LABEL_OPEN = "Project"
PROJECT_SECTION_LABEL_CLOSED = "Project (first open a project)"

NO_USERNAME_TEXT = "(NO USERNAME)"

SETTINGS_ORGANIZATION = "OpenCoder"
SETTINGS_APPLICATION = "OpenCoder"
RECENT_PROJECTS_KEY = "recentProjects"
MAX_RECENT_PROJECTS = 10

BASE_COLOR_CLASSES = [
    "#D81B60",
    "#1E88E5",
    "#FFC107",
    "#004D40",
    "#DE6E1C",
]

# Fraction of the way to blend a child's color toward white, relative to its
# parent's own shade, so nested codes read as progressively lighter tints of
# the same base color class.
CHILD_COLOR_LIGHTEN_FACTOR = 0.35


def _lighten_color(hex_color: str, factor: float = CHILD_COLOR_LIGHTEN_FACTOR) -> str:
    base = QColor(hex_color)
    r = base.red() + (255 - base.red()) * factor
    g = base.green() + (255 - base.green()) * factor
    b = base.blue() + (255 - base.blue()) * factor
    return QColor(int(r), int(g), int(b)).name()


HIGHLIGHT_ALPHA = 120

SNIPPET_MAX_LENGTH = 60
TOOLTIP_MAX_WIDTH_PX = 400
OTHER_DOCUMENT_TEXT_COLOR = QColor(150, 150, 150)

CODE_SORT_ALPHABETICAL = "alphabetical"
CODE_SORT_CURRENT_DOCUMENT = "current_document"
CODE_SORT_ALL_DOCUMENTS = "all_documents"

CODE_SORT_OPTIONS = [
    (CODE_SORT_ALPHABETICAL, "Alphabetical"),
    (CODE_SORT_CURRENT_DOCUMENT, "Segments in Current Document"),
    (CODE_SORT_ALL_DOCUMENTS, "Segments in All Documents"),
]

PANE_FOCUS_STYLE = """
QListWidget#documentPane, QPlainTextEdit#viewerPane,
QWidget#codebookPane, QWidget#segmentsPane {
    border: 2px solid transparent;
}
QListWidget#documentPane[focused="true"],
QPlainTextEdit#viewerPane[focused="true"],
QWidget#codebookPane[focused="true"],
QWidget#segmentsPane[focused="true"] {
    border: 2px solid #3399ff;
}
"""


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


def _segment_tooltip(full_text: str, doc_name: str, username: str) -> str:
    """Rich-text tooltip body: full segment text plus "[doc name, username]", word-wrapped."""
    escaped_text = html.escape(full_text)
    escaped_label = html.escape(f"{doc_name}, {username}")
    return (
        f'<div style="max-width: {TOOLTIP_MAX_WIDTH_PX}px;">'
        f"{escaped_text} [{escaped_label}]"
        f"</div>"
    )


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.conn: sqlite3.Connection | None = None
        self.project_path: Path | None = None
        self.username: str | None = None
        self._current_document_id: int | None = None
        self._code_sort_mode: str = CODE_SORT_ALPHABETICAL
        self._settings = QSettings(SETTINGS_ORGANIZATION, SETTINGS_APPLICATION)

        self.setWindowTitle("OpenCoder")
        self.resize(1150, 650)

        self.document_list = QListWidget()
        self.document_list.setObjectName("documentPane")
        self.document_list.currentItemChanged.connect(self._on_document_selected)

        self.viewer = VimTextViewer()
        self.viewer.setObjectName("viewerPane")
        self.viewer.selectionChanged.connect(self._on_viewer_selection_changed)
        self.viewer.cursorPositionChanged.connect(self._on_viewer_cursor_moved)
        self.viewer.modeChanged.connect(self._on_viewer_mode_changed)
        self.viewer.searchTextChanged.connect(self._on_viewer_search_text_changed)

        self.code_tree = CodeTreeWidget()
        self.code_tree.setHeaderHidden(True)
        self.code_tree.setColumnCount(2)
        self.code_tree.header().setStretchLastSection(False)
        self.code_tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.code_tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.code_tree.currentItemChanged.connect(self._on_code_selected)
        self.code_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.code_tree.customContextMenuRequested.connect(self._on_code_context_menu)
        self.code_tree.codeReparented.connect(self._on_code_reparented)

        self._code_items_by_id: dict[int, QTreeWidgetItem] = {}
        self._last_selected_code_id: int | None = None
        self._segments_panel_code_id: int | None = None

        self.code_sort_combo = QComboBox()
        for value, label in CODE_SORT_OPTIONS:
            self.code_sort_combo.addItem(label, value)
        self.code_sort_combo.currentIndexChanged.connect(self._on_code_sort_changed)

        self.code_filter_input = CodeFilterLineEdit()
        self.code_filter_input.setPlaceholderText("Filter codes, or type a new name and press Enter…")
        self.code_filter_input.textChanged.connect(self._on_code_filter_changed)
        self.code_filter_input.returnPressed.connect(self._on_code_filter_return_pressed)
        self.code_filter_input.cyclePressed.connect(self._on_code_filter_cycle)
        self.code_filter_input.escapePressed.connect(self._on_code_filter_escape)

        self.apply_code_button = QPushButton("Apply to Selection")
        self.apply_code_button.clicked.connect(self._on_apply_code)

        self.segment_code_label = QLabel()
        self.segment_code_label.setMargin(4)

        self.segment_list = QListWidget()
        self.segment_list.itemDoubleClicked.connect(self._on_segment_activated)

        code_panel = QWidget()
        code_layout = QVBoxLayout(code_panel)
        code_layout.setContentsMargins(0, 0, 0, 0)

        code_splitter = QSplitter(Qt.Vertical)

        tree_container = QWidget()
        tree_container.setObjectName("codebookPane")
        self.codebook_pane = tree_container
        tree_layout = QVBoxLayout(tree_container)
        tree_layout.setContentsMargins(0, 0, 0, 0)
        tree_layout.addWidget(QLabel("Codebook"))
        tree_layout.addWidget(self.code_sort_combo)
        tree_layout.addWidget(self.code_filter_input)
        tree_layout.addWidget(self.code_tree)
        tree_layout.addWidget(self.apply_code_button)
        code_splitter.addWidget(tree_container)

        segments_container = QWidget()
        segments_container.setObjectName("segmentsPane")
        self.segments_pane = segments_container
        segments_layout = QVBoxLayout(segments_container)
        segments_layout.setContentsMargins(0, 0, 0, 0)
        segments_layout.addWidget(QLabel("Coded Segments"))
        segments_layout.addWidget(self.segment_code_label)
        segments_layout.addWidget(self.segment_list)
        code_splitter.addWidget(segments_container)

        code_layout.addWidget(code_splitter)

        self.username_label = QLabel()
        self.username_label.setAlignment(Qt.AlignCenter)
        self._update_username_label()

        viewer_container = QWidget()
        viewer_layout = QVBoxLayout(viewer_container)
        viewer_layout.setContentsMargins(0, 0, 0, 0)
        viewer_layout.addWidget(self.viewer)
        viewer_layout.addWidget(self.username_label)

        splitter = QSplitter()
        splitter.addWidget(self.document_list)
        splitter.addWidget(viewer_container)
        splitter.addWidget(code_panel)
        splitter.setStretchFactor(1, 1)
        self.setCentralWidget(splitter)

        self._build_menu()
        self._update_actions_enabled()
        self.statusBar().showMessage("No project open")

        self.vim_mode_label = QLabel()
        self.statusBar().addPermanentWidget(self.vim_mode_label)

        self.search_label = QLabel()
        self.statusBar().addPermanentWidget(self.search_label)

        self.setStyleSheet(PANE_FOCUS_STYLE)
        self._panes = (self.document_list, self.viewer, self.codebook_pane, self.segments_pane)

        QApplication.instance().installEventFilter(self)
        QApplication.instance().focusChanged.connect(self._on_focus_changed)

    def closeEvent(self, event) -> None:
        QApplication.instance().removeEventFilter(self)
        QApplication.instance().focusChanged.disconnect(self._on_focus_changed)
        super().closeEvent(event)

    def _on_focus_changed(self, _old, new) -> None:
        for pane in self._panes:
            focused = new is not None and (pane is new or pane.isAncestorOf(new))
            pane.setProperty("focused", focused)
            pane.style().unpolish(pane)
            pane.style().polish(pane)

    def eventFilter(self, watched, event) -> bool:
        if event.type() == QEvent.KeyPress:
            # While the viewer is composing a search string, key presses that would
            # otherwise act on its (search-preview) selection must fall through to
            # VimTextViewer's own key handling instead, so typed text always reaches
            # the search buffer rather than being hijacked as a coding shortcut.
            viewer_searching = (
                QApplication.focusWidget() is self.viewer
                and self.viewer.mode == VimTextViewer.SEARCH
            )
            if event.key() == Qt.Key_Space:
                if not viewer_searching and QApplication.focusWidget() is not self.code_filter_input:
                    self.code_filter_input.setFocus()
                    self.code_filter_input.selectAll()
                    return True
            elif event.key() == Qt.Key_Escape:
                if QApplication.focusWidget() is self.document_list:
                    self.viewer.setFocus()
                    return True
            elif event.key() in (Qt.Key_Up, Qt.Key_Down):
                if (
                    not viewer_searching
                    and QApplication.focusWidget() is self.viewer
                    and self.viewer.textCursor().hasSelection()
                ):
                    self._cycle_matched_code(-1 if event.key() == Qt.Key_Up else 1)
                    return True
            elif event.key() in (Qt.Key_Return, Qt.Key_Enter):
                if not viewer_searching and QApplication.focusWidget() is self.viewer:
                    current = self.code_tree.currentItem()
                    if current is not None and self._apply_code_to_viewer_selection(
                        current.data(0, Qt.UserRole)
                    ):
                        self.viewer.exit_visual_mode()
                        return True
            elif event.key() == Qt.Key_X:
                if QApplication.focusWidget() is self.viewer:
                    if self.viewer.mode == VimTextViewer.VISUAL:
                        self._delete_segments_in_viewer_selection()
                        self.viewer.exit_visual_mode()
                        return True
                    elif self.viewer.mode == VimTextViewer.NORMAL:
                        self._delete_segments_at_cursor()
                        return True
            elif event.key() == Qt.Key_C:
                if QApplication.focusWidget() is self.viewer and self.viewer.mode == VimTextViewer.NORMAL:
                    shift = bool(event.modifiers() & Qt.ShiftModifier)
                    self._jump_to_adjacent_segment(-1 if shift else 1)
                    return True
            elif event.key() == Qt.Key_Question:
                if not viewer_searching and QApplication.focusWidget() is self.viewer:
                    self._on_show_shortcuts()
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

        self.recent_projects_menu = QMenu("Open &Recent", self)
        file_menu.addMenu(self.recent_projects_menu)
        self._refresh_recent_projects_menu()

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

        self.export_code_frequency_menu = QMenu("Export Code Frequency Report", self)
        file_menu.addMenu(self.export_code_frequency_menu)

        self.export_code_frequency_csv_action = QAction("Code Frequency Report (CSV)…", self)
        self.export_code_frequency_csv_action.triggered.connect(
            self._on_export_code_frequency_csv
        )
        self.export_code_frequency_menu.addAction(self.export_code_frequency_csv_action)

        self.export_code_frequency_json_action = QAction("Code Frequency Report (JSON)…", self)
        self.export_code_frequency_json_action.triggered.connect(
            self._on_export_code_frequency_json
        )
        self.export_code_frequency_menu.addAction(self.export_code_frequency_json_action)

        self.export_code_user_frequency_csv_action = QAction(
            "Code/User Frequency Report (CSV)…", self
        )
        self.export_code_user_frequency_csv_action.triggered.connect(
            self._on_export_code_user_frequency_csv
        )
        self.export_code_frequency_menu.addAction(self.export_code_user_frequency_csv_action)

        self.export_code_user_frequency_json_action = QAction(
            "Code/User Frequency Report (JSON)…", self
        )
        self.export_code_user_frequency_json_action.triggered.connect(
            self._on_export_code_user_frequency_json
        )
        self.export_code_frequency_menu.addAction(self.export_code_user_frequency_json_action)

        self.close_project_action = QAction("&Close Project", self)
        self.close_project_action.triggered.connect(self.close_project)
        file_menu.addAction(self.close_project_action)

        file_menu.addSeparator()

        # -- Application ----------------------------------------------------
        quit_action = QAction("&Quit", self)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        view_menu = self.menuBar().addMenu("&View")

        self.code_frequency_action = QAction("&Code Frequency Report…", self)
        self.code_frequency_action.triggered.connect(self._on_code_frequency_report)
        view_menu.addAction(self.code_frequency_action)

        self.code_user_frequency_action = QAction("Code/&User Frequency Report…", self)
        self.code_user_frequency_action.triggered.connect(self._on_code_user_frequency_report)
        view_menu.addAction(self.code_user_frequency_action)

    # -- Dialog-triggering slots -------------------------------------------

    def _on_new_project(self) -> None:
        path_str, _ = QFileDialog.getSaveFileName(self, "New Project", "", PROJECT_FILTER)
        if not path_str:
            return
        if not path_str.endswith(".sqlite"):
            path_str += ".sqlite"
        path = Path(path_str)
        self.create_project(path)
        self._ensure_username(path)

    def _on_open_project(self) -> None:
        path_str, _ = QFileDialog.getOpenFileName(self, "Open Project", "", PROJECT_FILTER)
        if not path_str:
            return
        path = Path(path_str)
        self.open_project(path)
        self._ensure_username(path)

    def _on_open_recent_project(self, path: Path) -> None:
        self.open_project(path)
        self._ensure_username(path)

    def _ensure_username(self, path: Path) -> str | None:
        """Prompt for a username the first time this project's directory is
        opened, then reuse the stored name silently on later opens."""
        existing = user.read_username(path)
        if existing:
            self.username = existing
            self._update_username_label()
            return existing
        name, ok = QInputDialog.getText(self, "Username", "Enter your username:")
        name = name.strip() if ok else ""
        if not name:
            return None
        user.write_username(path, name)
        self.username = name
        self._update_username_label()
        return name

    def _update_username_label(self) -> None:
        self.username_label.setText(self.username or NO_USERNAME_TEXT)

    def _on_import_document(self) -> None:
        path_str, _ = QFileDialog.getOpenFileName(self, "Import Document", "", TEXT_FILTER)
        if not path_str:
            return
        path = Path(path_str)
        if self.conn is not None and db.get_document_by_name(self.conn, path.name) is not None:
            reply = QMessageBox.question(
                self,
                "Document Already Imported",
                f"A document named “{path.name}” has already been imported. "
                "Overwrite it?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return
            self.import_document(path, overwrite=True)
            return
        self.import_document(path)

    def _on_document_selected(
        self, current: QListWidgetItem | None, _previous: QListWidgetItem | None
    ) -> None:
        self.viewer.exit_visual_mode()
        if current is None or self.conn is None:
            self._current_document_id = None
            self.viewer.clear()
            self.viewer.set_code_highlights([])
            self._refresh_codes()
            self._on_viewer_cursor_moved()
            return
        doc_id = current.data(Qt.UserRole)
        doc = db.get_document(self.conn, doc_id)
        self._current_document_id = doc_id
        self.viewer.setPlainText(doc.content if doc else "")
        self._refresh_highlights()
        self._refresh_codes()
        self._on_viewer_cursor_moved()

    def _on_viewer_mode_changed(self, mode: str) -> None:
        if mode == VimTextViewer.VISUAL:
            self.vim_mode_label.setText("-- VISUAL --")
        elif mode == VimTextViewer.SEARCH:
            self.vim_mode_label.setText("-- SEARCH --")
        else:
            self.vim_mode_label.setText("")

    def _on_viewer_search_text_changed(self, text: str) -> None:
        self.search_label.setText(f"/{text}" if text else "")

    def _on_code_selected(
        self, current: QTreeWidgetItem | None, _previous: QTreeWidgetItem | None
    ) -> None:
        if current is not None:
            self._last_selected_code_id = current.data(0, Qt.UserRole)
        self._show_segments_for_code(current.data(0, Qt.UserRole) if current is not None else None)

    def _on_code_filter_escape(self) -> None:
        self.viewer.setFocus()

    def _on_code_sort_changed(self, index: int) -> None:
        self._code_sort_mode = self.code_sort_combo.itemData(index)
        self._refresh_codes()

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
            if self._apply_code_to_viewer_selection(code_id):
                self.viewer.exit_visual_mode()
                self.viewer.setFocus()
            else:
                self._select_code(code_id)
            return

        code = self.add_code(text)
        self.code_filter_input.clear()
        self._select_code(code.id)
        if self._apply_code_to_viewer_selection(code.id):
            self.viewer.exit_visual_mode()
            self.viewer.setFocus()

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
        delete_action = menu.addAction("Delete…")

        chosen = menu.exec(self.code_tree.viewport().mapToGlobal(pos))
        if chosen is None:
            return
        if chosen is new_child_action:
            self._on_new_child_code(item.data(0, Qt.UserRole))
        elif chosen is rename_action:
            self._on_rename_code(item.data(0, Qt.UserRole), item.text(0))
        elif chosen is delete_action:
            self._on_delete_code(item.data(0, Qt.UserRole), item.text(0))

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

    def _on_delete_code(self, code_id: int, name: str) -> None:
        reply = QMessageBox.question(
            self,
            "Delete Code",
            f"Delete “{name}”? Its coded segments will be removed, and any "
            "child codes will move up to take its place.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        self.delete_code(code_id)

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

    def _on_export_code_frequency_csv(self) -> None:
        if self.conn is None:
            return
        path_str, _ = QFileDialog.getSaveFileName(
            self, "Export Code Frequency Report (CSV)", "", CSV_FILTER
        )
        if not path_str:
            return
        if not path_str.endswith(".csv"):
            path_str += ".csv"
        count = reporting.export_code_frequency_csv(self.conn, path_str)
        QMessageBox.information(self, "Export Complete", f"Exported {count} code(s).")

    def _on_export_code_frequency_json(self) -> None:
        if self.conn is None:
            return
        path_str, _ = QFileDialog.getSaveFileName(
            self, "Export Code Frequency Report (JSON)", "", JSON_FILTER
        )
        if not path_str:
            return
        if not path_str.endswith(".json"):
            path_str += ".json"
        count = reporting.export_code_frequency_json(self.conn, path_str)
        QMessageBox.information(self, "Export Complete", f"Exported {count} code(s).")

    def _on_export_code_user_frequency_csv(self) -> None:
        if self.conn is None:
            return
        path_str, _ = QFileDialog.getSaveFileName(
            self, "Export Code/User Frequency Report (CSV)", "", CSV_FILTER
        )
        if not path_str:
            return
        if not path_str.endswith(".csv"):
            path_str += ".csv"
        count = reporting.export_code_user_frequency_csv(self.conn, path_str)
        QMessageBox.information(self, "Export Complete", f"Exported {count} row(s).")

    def _on_export_code_user_frequency_json(self) -> None:
        if self.conn is None:
            return
        path_str, _ = QFileDialog.getSaveFileName(
            self, "Export Code/User Frequency Report (JSON)", "", JSON_FILTER
        )
        if not path_str:
            return
        if not path_str.endswith(".json"):
            path_str += ".json"
        count = reporting.export_code_user_frequency_json(self.conn, path_str)
        QMessageBox.information(self, "Export Complete", f"Exported {count} row(s).")

    def _on_code_frequency_report(self) -> None:
        if self.conn is None:
            return
        rows = reporting.code_frequency(self.conn)
        dialog = CodeFrequencyDialog(rows, self)
        dialog.exec()

    def _on_code_user_frequency_report(self) -> None:
        if self.conn is None:
            return
        rows = reporting.code_user_frequency(self.conn)
        dialog = CodeUserFrequencyDialog(rows, self)
        dialog.exec()

    def _on_show_shortcuts(self) -> None:
        dialog = ShortcutsDialog(self)
        dialog.exec()

    # -- Testable logic, independent of QFileDialog / QMessageBox ---------

    def create_project(self, path: Path) -> None:
        if path.exists():
            path.unlink()
        self._set_connection(db.connect(path), path)

    def open_project(self, path: Path) -> None:
        self._set_connection(db.connect(path), path)

    def close_project(self) -> None:
        if self.conn is None:
            return
        self.conn.close()
        self.conn = None
        self.project_path = None
        self.username = None
        self._update_username_label()
        self._current_document_id = None
        self._last_selected_code_id = None
        self.viewer.clear()
        self.viewer.set_code_highlights([])
        self._refresh_documents()
        self._refresh_codes()
        self._update_actions_enabled()
        self.setWindowTitle("OpenCoder")
        self.statusBar().showMessage("No project open")

    def import_document(self, path: Path, *, overwrite: bool = False) -> bool:
        if self.conn is None:
            return False
        existing = db.get_document_by_name(self.conn, path.name)
        if existing is not None and not overwrite:
            return False
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            QMessageBox.warning(
                self, "Import Failed", f"Could not read {path.name} as UTF-8 text."
            )
            return False
        if existing is not None:
            db.delete_document(self.conn, existing.id)
        doc = db.create_document(self.conn, path.name, content)
        self._refresh_documents()
        self._select_document(doc.id)
        return True

    def add_code(self, name: str, parent_id: int | None = None) -> Code:
        if self.conn is None:
            raise RuntimeError("No project open")
        parent = db.get_code(self.conn, parent_id) if parent_id is not None else None
        color_class, color = self._color_for_parent(parent)
        code = db.create_code(
            self.conn, name, parent_id=parent_id, color=color, color_class=color_class
        )
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
        db.set_code_parent(self.conn, code_id, parent_id)
        code = self._recolor_subtree(code_id, parent_id)
        self._refresh_codes()
        self._refresh_highlights()
        return code

    def _color_for_parent(self, parent: Code | None) -> tuple[str, str]:
        """Return (color_class, color) for a code with the given parent.

        Root codes (parent is None) get a freshly balanced base color class;
        child codes inherit the parent's color class, lightened one step.
        """
        if parent is not None:
            return parent.color_class, _lighten_color(parent.color)
        color_class = self._next_color_class()
        return color_class, color_class

    def _recolor_subtree(self, code_id: int, parent_id: int | None) -> Code:
        """Recolor `code_id` per its new parent, then cascade to its descendants
        so the whole moved subtree keeps the parent-inherits-lighter invariant."""
        parent = db.get_code(self.conn, parent_id) if parent_id is not None else None
        color_class, color = self._color_for_parent(parent)
        code = db.set_code_color(self.conn, code_id, color, color_class)

        children_by_parent: dict[int, list[Code]] = {}
        for other in db.list_codes(self.conn):
            if other.parent_id is not None:
                children_by_parent.setdefault(other.parent_id, []).append(other)

        def recolor_children(ancestor_id: int, ancestor_color: str) -> None:
            for child in children_by_parent.get(ancestor_id, []):
                child_color = _lighten_color(ancestor_color)
                db.set_code_color(self.conn, child.id, child_color, color_class)
                recolor_children(child.id, child_color)

        recolor_children(code_id, color)
        return code

    def delete_code(self, code_id: int) -> None:
        if self.conn is None:
            raise RuntimeError("No project open")
        db.delete_code(self.conn, code_id)
        if self._last_selected_code_id == code_id:
            self._last_selected_code_id = None
        self._refresh_codes()
        self._refresh_highlights()

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
        db.create_segment(
            self.conn, self._current_document_id, code_id, start, end, created_by=self.username
        )
        self._refresh_codes()
        self._refresh_highlights()
        self._render_segments_panel()

    def _apply_code_to_viewer_selection(self, code_id: int) -> bool:
        cursor = self.viewer.textCursor()
        if not cursor.hasSelection():
            return False
        self.apply_segment(code_id, cursor.selectionStart(), cursor.selectionEnd())
        return True

    def _delete_segments_at_cursor(self) -> None:
        if self.conn is None or self._current_document_id is None:
            return
        position = self.viewer.textCursor().position()
        segments = db.list_segments_for_document(self.conn, self._current_document_id)
        intersecting = [s for s in segments if s.start_offset <= position < s.end_offset]
        if not intersecting:
            return
        for segment in intersecting:
            db.delete_segment(self.conn, segment.id)
        self._refresh_codes()
        self._refresh_highlights()
        self._render_segments_panel()

    def _delete_segments_in_viewer_selection(self) -> None:
        if self.conn is None or self._current_document_id is None:
            return
        cursor = self.viewer.textCursor()
        if not cursor.hasSelection():
            return
        start, end = cursor.selectionStart(), cursor.selectionEnd()
        segments = db.list_segments_for_document(self.conn, self._current_document_id)
        intersecting = [s for s in segments if s.start_offset < end and start < s.end_offset]
        if not intersecting:
            return
        for segment in intersecting:
            db.delete_segment(self.conn, segment.id)
        self._refresh_codes()
        self._refresh_highlights()
        self._render_segments_panel()

    def _jump_to_adjacent_segment(self, direction: int) -> None:
        segment = self._adjacent_segment(direction)
        if segment is None:
            return
        cursor = self.viewer.textCursor()
        cursor.setPosition(segment.end_offset)
        cursor.setPosition(segment.start_offset, QTextCursor.KeepAnchor)
        self.viewer.setTextCursor(cursor)
        self.viewer.ensureCursorVisible()

    def _adjacent_segment(self, direction: int):
        """Segment before/after the cursor, wrapping around the document."""
        if self.conn is None or self._current_document_id is None:
            return None
        segments = sorted(
            db.list_segments_for_document(self.conn, self._current_document_id),
            key=lambda s: (s.start_offset, s.end_offset),
        )
        if not segments:
            return None

        cursor = self.viewer.textCursor()
        position = cursor.selectionStart() if cursor.hasSelection() else cursor.position()
        if direction > 0:
            later = [s for s in segments if s.start_offset > position]
            return later[0] if later else segments[0]
        earlier = [s for s in segments if s.start_offset < position]
        return earlier[-1] if earlier else segments[-1]

    def _set_connection(self, conn: sqlite3.Connection, path: Path) -> None:
        if self.conn is not None:
            self.conn.close()
        self.conn = conn
        self.project_path = path
        self.username = None
        self._update_username_label()
        self._current_document_id = None
        self.setWindowTitle(f"OpenCoder — {path.name}")
        self.statusBar().showMessage(str(path))
        self._refresh_documents()
        self._refresh_codes()
        self._update_actions_enabled()
        self._add_recent_project(path)

    def _recent_projects(self) -> list[Path]:
        raw = self._settings.value(RECENT_PROJECTS_KEY, [])
        if isinstance(raw, str):
            raw = [raw]
        paths = [Path(entry) for entry in raw]
        existing = [path for path in paths if path.exists()]
        if existing != paths:
            self._settings.setValue(RECENT_PROJECTS_KEY, [str(path) for path in existing])
        return existing

    def _add_recent_project(self, path: Path) -> None:
        path = path.resolve()
        remaining = [p for p in self._recent_projects() if p != path]
        updated = [path, *remaining][:MAX_RECENT_PROJECTS]
        self._settings.setValue(RECENT_PROJECTS_KEY, [str(p) for p in updated])
        self._refresh_recent_projects_menu()

    def _refresh_recent_projects_menu(self) -> None:
        self.recent_projects_menu.clear()
        recent = self._recent_projects()
        if not recent:
            empty_action = QAction("No Recent Projects", self)
            empty_action.setEnabled(False)
            self.recent_projects_menu.addAction(empty_action)
            return
        for path in recent:
            action = QAction(str(path), self)
            action.triggered.connect(lambda _checked=False, p=path: self._on_open_recent_project(p))
            self.recent_projects_menu.addAction(action)

    def _refresh_documents(self) -> None:
        self.document_list.clear()
        if self.conn is None:
            return
        for doc in db.list_documents(self.conn):
            item = QListWidgetItem(doc.name)
            item.setData(Qt.UserRole, doc.id)
            self.document_list.addItem(item)

    def _code_sort_key(self, current_doc_counts: dict[int, int], total_counts: dict[int, int]):
        if self._code_sort_mode == CODE_SORT_CURRENT_DOCUMENT:
            return lambda code: (-current_doc_counts.get(code.id, 0), code.name.lower())
        if self._code_sort_mode == CODE_SORT_ALL_DOCUMENTS:
            return lambda code: (-total_counts.get(code.id, 0), code.name.lower())
        return lambda code: code.name.lower()

    def _refresh_codes(self) -> None:
        previous_current = self.code_tree.currentItem()
        previous_code_id = (
            previous_current.data(0, Qt.UserRole) if previous_current is not None else None
        )

        self.code_tree.clear()
        self.segment_list.clear()
        self._code_items_by_id = {}
        if self.conn is None:
            return

        codes = db.list_codes(self.conn)
        children_by_parent: dict[int | None, list[Code]] = {}
        for code in codes:
            children_by_parent.setdefault(code.parent_id, []).append(code)

        current_doc_counts = (
            db.count_segments_by_code(self.conn, self._current_document_id)
            if self._current_document_id is not None
            else {}
        )
        total_counts = db.count_segments_by_code(self.conn)

        sort_key = self._code_sort_key(current_doc_counts, total_counts)
        for children in children_by_parent.values():
            children.sort(key=sort_key)

        def add_children(parent_id: int | None, parent_item: QTreeWidgetItem | None) -> None:
            for code in children_by_parent.get(parent_id, []):
                count_label = f"{current_doc_counts.get(code.id, 0)}/{total_counts.get(code.id, 0)}"
                item = QTreeWidgetItem([code.name, count_label])
                item.setData(0, Qt.UserRole, code.id)
                item.setTextAlignment(1, Qt.AlignRight | Qt.AlignVCenter)
                if code.color:
                    item.setBackground(0, QColor(code.color))
                self._code_items_by_id[code.id] = item
                if parent_item is not None:
                    parent_item.addChild(item)
                else:
                    self.code_tree.addTopLevelItem(item)
                add_children(code.id, item)

        add_children(None, None)

        self.code_tree.expandAll()
        if previous_code_id is not None:
            restored = self._code_items_by_id.get(previous_code_id)
            if restored is not None:
                self.code_tree.setCurrentItem(restored)
        self._apply_code_filter(self.code_filter_input.text())
        self._sync_matched_code_selection()

    def _refresh_highlights(self) -> None:
        if self.conn is None or self._current_document_id is None:
            self.viewer.set_code_highlights([])
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

        self.viewer.set_code_highlights(selections)

    def _segment_at_viewer_cursor(self) -> db.Segment | None:
        if self.conn is None or self._current_document_id is None:
            return None
        position = self.viewer.textCursor().position()
        overlapping = [
            segment
            for segment in db.list_segments_for_document(self.conn, self._current_document_id)
            if segment.start_offset <= position < segment.end_offset
        ]
        if not overlapping:
            return None
        return min(overlapping, key=lambda s: s.end_offset - s.start_offset)

    def _on_viewer_cursor_moved(self) -> None:
        if QApplication.focusWidget() is self.viewer:
            segment = self._segment_at_viewer_cursor()
            if segment is not None:
                self._show_segments_for_code(segment.code_id)
                return
        item = self.code_tree.currentItem()
        self._show_segments_for_code(item.data(0, Qt.UserRole) if item is not None else None)

    def _show_segments_for_code(self, code_id: int | None) -> None:
        self._segments_panel_code_id = code_id
        self._render_segments_panel()

    def _render_segments_panel(self) -> None:
        self.segment_list.clear()
        code_id = self._segments_panel_code_id
        code = None
        if self.conn is not None and code_id is not None:
            code = next((c for c in db.list_codes(self.conn) if c.id == code_id), None)

        if code is None:
            self.segment_code_label.clear()
            self.segment_code_label.setStyleSheet("")
            return

        self.segment_code_label.setText(code.name)
        self.segment_code_label.setStyleSheet(
            f"background-color: {code.color}; border-radius: 3px;" if code.color else ""
        )

        documents_by_id = {doc.id: doc for doc in db.list_documents(self.conn)}
        segments = db.list_segments_for_code(self.conn, code_id)
        segments.sort(key=lambda s: s.document_id != self._current_document_id)

        for segment in segments:
            doc = documents_by_id.get(segment.document_id)
            doc_name = doc.name if doc else "?"
            username = segment.created_by or NO_USERNAME_TEXT
            full_text = doc.content[segment.start_offset : segment.end_offset] if doc else ""
            snippet = full_text
            if len(snippet) > SNIPPET_MAX_LENGTH:
                snippet = snippet[:SNIPPET_MAX_LENGTH] + "…"

            list_item = QListWidgetItem(f"“{snippet}” [{doc_name}, {username}]")
            list_item.setData(
                Qt.UserRole, (segment.document_id, segment.start_offset, segment.end_offset)
            )
            list_item.setToolTip(_segment_tooltip(full_text, doc_name, username))
            if segment.document_id != self._current_document_id:
                list_item.setForeground(OTHER_DOCUMENT_TEXT_COLOR)
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
        """Guarantee some code is selected, without disturbing an existing selection.

        Prefers restoring whichever code was last selected, so repeated
        coding with the same code doesn't require re-picking it each time.
        """
        if self.code_tree.currentItem() is not None:
            return
        matches = self._matching_code_items(self.code_filter_input.text())
        if not matches:
            return
        last_item = self._code_items_by_id.get(self._last_selected_code_id)
        if last_item in matches:
            self.code_tree.setCurrentItem(last_item)
            return
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

    def _next_color_class(self) -> str:
        counts = db.count_codes_by_color_class(self.conn) if self.conn else {}
        class_counts = {cls: counts.get(cls, 0) for cls in BASE_COLOR_CLASSES}
        max_count = max(class_counts.values())
        candidates = [cls for cls, count in class_counts.items() if count < max_count]
        return random.choice(candidates or BASE_COLOR_CLASSES)

    def _update_actions_enabled(self) -> None:
        has_project = self.conn is not None
        self.import_action.setEnabled(has_project)
        self.export_csv_action.setEnabled(has_project)
        self.export_json_action.setEnabled(has_project)
        self.export_code_frequency_menu.setEnabled(has_project)
        self.close_project_action.setEnabled(has_project)
        self.code_frequency_action.setEnabled(has_project)
        self.code_user_frequency_action.setEnabled(has_project)
        self.project_section_action.setText(
            PROJECT_SECTION_LABEL_OPEN if has_project else PROJECT_SECTION_LABEL_CLOSED
        )
