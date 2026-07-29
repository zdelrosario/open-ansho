from __future__ import annotations

import html
import random
import sqlite3
from pathlib import Path

from PySide6.QtCore import QEvent, QSettings, Qt
from PySide6.QtGui import QAction, QColor, QFont, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
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
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from openansho import db, reporting, user
from openansho.db import Code
from openansho.ui.checkable_combo_box import CheckableComboBox
from openansho.ui.code_filter_input import CodeFilterLineEdit
from openansho.ui.code_tree import CodeTreeWidget
from openansho.ui.merge_codes_dialog import MergeCodesDialog
from openansho.ui.os_theme import detect_dark_mode
from openansho.ui.preferences_dialog import PreferencesDialog
from openansho.ui.report_dialog import CodeFrequencyDialog, CodeUserFrequencyDialog
from openansho.ui.shortcuts_dialog import ShortcutsDialog
from openansho.ui.vim_viewer import CodeHighlight, VimTextViewer

PROJECT_FILTER = "OpenAnsho Project (*.sqlite)"
TEXT_FILTER = "Text Files (*.txt);;All Files (*)"
CSV_FILTER = "CSV Files (*.csv)"
JSON_FILTER = "JSON Files (*.json)"

PROJECT_SECTION_LABEL_OPEN = "Project"
PROJECT_SECTION_LABEL_CLOSED = "Project (first open a project)"

NO_USERNAME_TEXT = "(NO USERNAME)"

SETTINGS_ORGANIZATION = "OpenAnsho"
SETTINGS_APPLICATION = "OpenAnsho"
RECENT_PROJECTS_KEY = "recentProjects"
MAX_RECENT_PROJECTS = 10
DARK_MODE_KEY = "darkMode"

BASE_COLOR_CLASSES = [
    "#D81B60",
    "#1E88E5",
    "#FFC107",
    "#004D40",
    "#DE6E1C",
    "#A65BC0",
]

# A neutral grey, assignable manually but excluded from BASE_COLOR_CLASSES so
# automatic/random assignment never picks it.
GREY_COLOR_CLASS = "#757575"

# Every color class a user can pick from the "Assign Base Color" menu,
# including grey. Automatic assignment must use BASE_COLOR_CLASSES instead.
ASSIGNABLE_COLOR_CLASSES = BASE_COLOR_CLASSES + [GREY_COLOR_CLASS]

BASE_COLOR_CLASS_NAMES = {
    "#D81B60": "Red",
    "#1E88E5": "Blue",
    "#FFC107": "Yellow",
    "#004D40": "Green",
    "#DE6E1C": "Orange",
    "#A65BC0": "Purple",
    GREY_COLOR_CLASS: "Grey",
}

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
CODE_NAME_TEXT_COLOR = QColor(255, 255, 255)

NEW_CODE_LABEL = "(add new code)"
NEW_CODE_MARKER = "__new_code_marker__"

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
QTreeWidget#codeTreePane, QListWidget#segmentListPane {
    border: 2px solid transparent;
}
QListWidget#documentPane[focused="true"],
QPlainTextEdit#viewerPane[focused="true"],
QTreeWidget#codeTreePane[focused="true"],
QListWidget#segmentListPane[focused="true"] {
    border: 2px solid #3399ff;
}
"""

DARK_THEME_STYLE = """
QWidget {
    background-color: #000000;
    color: #ffffff;
}
QMenuBar, QMenu, QMenu::item {
    background-color: #000000;
    color: #ffffff;
}
QMenu::item:selected {
    background-color: #333333;
}
QLineEdit, QPlainTextEdit, QTreeWidget, QListWidget, QComboBox, QHeaderView::section, QPushButton {
    background-color: #000000;
    color: #ffffff;
    border: 1px solid #444444;
}
QTreeWidget::item:selected, QListWidget::item:selected {
    background-color: #333333;
}
QPlainTextEdit#viewerPane {
    selection-background-color: #ffffff;
    selection-color: #000000;
}
"""

LIGHT_THEME_STYLE = """
QWidget {
    background-color: #ffffff;
    color: #000000;
}
QMenuBar, QMenu, QMenu::item {
    background-color: #ffffff;
    color: #000000;
}
QMenu::item:selected {
    background-color: #e0e0e0;
}
QLineEdit, QPlainTextEdit, QTreeWidget, QListWidget, QComboBox, QHeaderView::section, QPushButton {
    background-color: #ffffff;
    color: #000000;
    border: 1px solid #cccccc;
}
QTreeWidget::item:selected, QListWidget::item:selected {
    background-color: #d0e8ff;
}
QPlainTextEdit#viewerPane {
    selection-background-color: #000000;
    selection-color: #ffffff;
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
        if self._settings.contains(DARK_MODE_KEY):
            self._dark_mode: bool = self._settings.value(DARK_MODE_KEY, type=bool)
        else:
            self._dark_mode = detect_dark_mode()

        self.setWindowTitle("OpenAnsho")
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
        self.viewer.contentEdited.connect(self._on_viewer_content_edited)

        self.code_tree = CodeTreeWidget()
        self.code_tree.setHeaderHidden(True)
        self.code_tree.setColumnCount(2)
        self.code_tree.header().setStretchLastSection(False)
        self.code_tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.code_tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.code_tree.setObjectName("codeTreePane")
        self.code_tree.currentItemChanged.connect(self._on_code_selected)
        self.code_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.code_tree.customContextMenuRequested.connect(self._on_code_context_menu)
        self.code_tree.codeReparented.connect(self._on_code_reparented)

        self._code_items_by_id: dict[int, QTreeWidgetItem] = {}
        self._new_code_item: QTreeWidgetItem | None = None
        self._last_selected_code_id: int | None = None
        # "code": browsing every segment coded with a single code (picked from
        # the codebook tree), across the whole document. "cursor": showing
        # every code applied to whatever the viewer's cursor/selection is
        # currently touching, so simultaneously-applied codes on the same
        # span are all visible at once instead of only the most recent.
        self._segments_panel_mode: str = "code"
        self._segments_panel_code_id: int | None = None
        self._user_filter_overrides: dict[str, bool] = {}

        self.code_sort_combo = QComboBox()
        for value, label in CODE_SORT_OPTIONS:
            self.code_sort_combo.addItem(label, value)
        self.code_sort_combo.currentIndexChanged.connect(self._on_code_sort_changed)

        self.code_filter_input = CodeFilterLineEdit()
        self.code_filter_input.setPlaceholderText("Filter codes, or type a new name and press Enter…")
        self.code_filter_input.textChanged.connect(self._on_code_filter_changed)
        self.code_filter_input.returnPressed.connect(self._on_code_filter_return_pressed)
        self.code_filter_input.cyclePressed.connect(self._on_code_filter_cycle)

        self.apply_code_button = QPushButton("Apply to Selection")
        self.apply_code_button.clicked.connect(self._on_apply_code)

        self.segment_code_label = QLabel()
        self.segment_code_label.setMargin(4)

        self.segment_list = QListWidget()
        self.segment_list.setObjectName("segmentListPane")
        self.segment_list.itemDoubleClicked.connect(self._on_segment_activated)
        self.segment_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.segment_list.customContextMenuRequested.connect(self._on_segment_list_context_menu)

        self.user_filter_combo = CheckableComboBox()
        self.user_filter_combo.model().dataChanged.connect(self._on_user_filter_changed)

        code_panel = QWidget()
        code_layout = QVBoxLayout(code_panel)
        code_layout.setContentsMargins(0, 0, 0, 0)

        code_splitter = QSplitter(Qt.Vertical)

        tree_container = QWidget()
        tree_layout = QVBoxLayout(tree_container)
        tree_layout.setContentsMargins(0, 0, 0, 0)
        tree_layout.addWidget(QLabel("Codebook"))
        tree_layout.addWidget(self.code_sort_combo)
        tree_layout.addWidget(self.code_filter_input)
        tree_layout.addWidget(self.code_tree)
        tree_layout.addWidget(self.apply_code_button)
        code_splitter.addWidget(tree_container)

        segments_container = QWidget()
        segments_layout = QVBoxLayout(segments_container)
        segments_layout.setContentsMargins(0, 0, 0, 0)
        segments_layout.addWidget(QLabel("Coded Segments"))
        segments_layout.addWidget(self.user_filter_combo)
        segments_layout.addWidget(self.segment_code_label)
        segments_layout.addWidget(self.segment_list)
        code_splitter.addWidget(segments_container)

        code_layout.addWidget(code_splitter)

        self.username_label = QLabel()
        self.username_label.setAlignment(Qt.AlignCenter)
        self._update_username_label()

        self.insert_mode_button = QPushButton("Insert Mode")
        self.insert_mode_button.setCheckable(True)
        self.insert_mode_button.toggled.connect(self._on_insert_mode_button_toggled)

        viewer_bottom_bar = QHBoxLayout()
        viewer_bottom_bar.addStretch()
        viewer_bottom_bar.addWidget(self.insert_mode_button)

        viewer_container = QWidget()
        viewer_layout = QVBoxLayout(viewer_container)
        viewer_layout.setContentsMargins(0, 0, 0, 0)
        viewer_layout.addWidget(self.viewer)
        viewer_layout.addWidget(self.username_label)
        viewer_layout.addLayout(viewer_bottom_bar)

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

        self._apply_theme()
        self._panes = (self.document_list, self.viewer, self.code_tree, self.segment_list)

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
        self._update_new_code_placeholder()

    def eventFilter(self, watched, event) -> bool:
        if event.type() == QEvent.KeyPress:
            # While the viewer is awaiting the f/F target character, every global
            # shortcut below must stand down for this one keypress so the
            # character reaches VimTextViewer's own key handling intact, whatever
            # key it happens to be (including keys like x/c/Enter that would
            # otherwise be hijacked as coding shortcuts).
            if QApplication.focusWidget() is self.viewer and self.viewer.awaiting_find_char:
                return super().eventFilter(watched, event)

            # In insert mode the viewer is an ordinary text editor; every key
            # (including ones global shortcuts would otherwise hijack, like
            # Space/Enter/x/c/?) must reach VimTextViewer's own key handling
            # so typing/editing works normally.
            if QApplication.focusWidget() is self.viewer and self.viewer.mode == VimTextViewer.INSERT:
                return super().eventFilter(watched, event)

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
                if QApplication.focusWidget() is not self.viewer:
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

        settings_menu = self.menuBar().addMenu("&Settings")

        preferences_action = QAction("&Preferences…", self)
        preferences_action.setMenuRole(QAction.MenuRole.NoRole)
        preferences_action.triggered.connect(self._on_show_preferences)
        settings_menu.addAction(preferences_action)

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
            self._apply_active_user_default_filter()
            return existing
        name, ok = QInputDialog.getText(self, "Username", "Enter your username:")
        name = name.strip() if ok else ""
        if not name:
            return None
        user.write_username(path, name)
        self.username = name
        self._update_username_label()
        self._apply_active_user_default_filter()
        return name

    def _apply_active_user_default_filter(self) -> None:
        """Re-derive the user filter's defaults now that `self.username` is known.

        `_set_connection` populates the filter before the active username is
        established (it's read from a sidecar file after the connection is
        opened), so its "select only the active user" default can't take
        effect until this runs.
        """
        self._refresh_user_filter()
        self._refresh_codes()
        self._refresh_highlights()
        self._render_segments_panel()

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
        self.viewer.exit_insert_mode()
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
        elif mode == VimTextViewer.INSERT:
            self.vim_mode_label.setText("-- INSERT --")
        else:
            self.vim_mode_label.setText("")
        self.insert_mode_button.blockSignals(True)
        self.insert_mode_button.setChecked(mode == VimTextViewer.INSERT)
        self.insert_mode_button.blockSignals(False)

    def _on_insert_mode_button_toggled(self, checked: bool) -> None:
        if checked:
            self.viewer.enter_insert_mode()
        else:
            self.viewer.exit_insert_mode()
        self.viewer.setFocus()

    def _on_viewer_search_text_changed(self, text: str) -> None:
        self.search_label.setText(f"/{text}" if text else "")

    def _on_code_selected(
        self, current: QTreeWidgetItem | None, _previous: QTreeWidgetItem | None
    ) -> None:
        if current is not None:
            self._last_selected_code_id = current.data(0, Qt.UserRole)
        self._show_segments_for_code(current.data(0, Qt.UserRole) if current is not None else None)

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
        self._update_new_code_placeholder()
        self._sync_matched_code_selection()

    def _on_code_filter_cycle(self, direction: int) -> None:
        self._cycle_matched_code(direction)

    def _on_code_filter_return_pressed(self) -> None:
        if self.conn is None:
            return
        text = self.code_filter_input.text().strip()
        if not text:
            return

        if self._new_code_item is not None and self.code_tree.currentItem() is self._new_code_item:
            self._create_and_apply_new_code(text)
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

        self._create_and_apply_new_code(text)

    def _create_and_apply_new_code(self, text: str) -> None:
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
        self._apply_code_to_viewer_selection(code_item.data(0, Qt.UserRole))

    def _on_code_context_menu(self, pos) -> None:
        if self.conn is None:
            return
        item = self.code_tree.itemAt(pos)
        if item is None:
            return
        code_id = item.data(0, Qt.UserRole)
        code = db.get_code(self.conn, code_id)

        menu = QMenu(self)
        new_child_action = menu.addAction("New Child Code…")
        rename_action = menu.addAction("Rename…")
        edit_description_action = menu.addAction("Edit Description…")

        color_menu = menu.addMenu("Assign Base Color")
        color_menu.setEnabled(code is not None and code.parent_id is None)
        color_actions = {}
        for color_class in ASSIGNABLE_COLOR_CLASSES:
            label = BASE_COLOR_CLASS_NAMES.get(color_class, color_class)
            is_current = code is not None and code.color_class == color_class
            action = QWidgetAction(color_menu)
            action.setCheckable(True)
            action.setChecked(is_current)
            button = QPushButton(("✓ " if is_current else "   ") + label, color_menu)
            button.setFlat(True)
            button.setStyleSheet(
                f"QPushButton {{ color: {color_class}; text-align: left; padding: 4px 20px;"
                f" border: none; background: transparent;"
                f" font-weight: {'bold' if is_current else 'normal'}; }}"
                "QPushButton:hover { background: rgba(128, 128, 128, 60); }"
            )
            button.clicked.connect(lambda checked=False, a=action: (a.trigger(), menu.close()))
            action.setDefaultWidget(button)
            color_menu.addAction(action)
            color_actions[action] = color_class

        merge_action = menu.addAction("Merge Codes…")
        delete_action = menu.addAction("Delete…")

        chosen = menu.exec(self.code_tree.viewport().mapToGlobal(pos))
        if chosen is None:
            return
        if chosen is new_child_action:
            self._on_new_child_code(code_id)
        elif chosen is rename_action:
            self._on_rename_code(code_id, item.text(0))
        elif chosen is edit_description_action:
            self._on_edit_code_description(code_id, code.description if code else None)
        elif chosen in color_actions:
            self.set_code_base_color(code_id, color_actions[chosen])
        elif chosen is merge_action:
            self._on_merge_codes(code_id)
        elif chosen is delete_action:
            self._on_delete_code(code_id, item.text(0))

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

    def _on_edit_code_description(self, code_id: int, current_description: str | None) -> None:
        description, ok = QInputDialog.getMultiLineText(
            self, "Edit Description", "Code description:", current_description or ""
        )
        if not ok:
            return
        self.edit_code_description(code_id, description.strip())

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

    def _on_merge_codes(self, code_id: int) -> None:
        if self.conn is None:
            return
        codes_by_id = {code.id: code for code in db.list_codes(self.conn)}
        if len(codes_by_id) < 2:
            QMessageBox.information(
                self, "Merge Codes", "There must be at least two codes to merge."
            )
            return
        options = sorted(
            ((cid, reporting.code_path(codes_by_id, cid)) for cid in codes_by_id),
            key=lambda pair: pair[1],
        )
        dialog = MergeCodesDialog(options, default_merge_id=code_id, parent=self)
        if dialog.exec() != QDialog.Accepted:
            return
        keep_id, merge_id = dialog.keep_id(), dialog.merge_id()

        other_user_codes = [
            codes_by_id[cid].name
            for cid in (keep_id, merge_id)
            if self._code_has_other_user_segments(cid)
        ]
        if other_user_codes:
            reply = QMessageBox.warning(
                self,
                "Merge Codes",
                "The following code(s) have segments coded by a user other "
                f"than the active user: {', '.join(other_user_codes)}.\n\n"
                "Merge anyway?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return

        try:
            self.merge_codes(keep_id, merge_id)
        except ValueError as exc:
            QMessageBox.warning(self, "Merge Codes", str(exc))

    def _code_has_other_user_segments(self, code_id: int) -> bool:
        return any(
            segment.created_by and segment.created_by != self.username
            for segment in db.list_segments_for_code(self.conn, code_id)
        )

    def _on_segment_activated(self, item: QListWidgetItem) -> None:
        data = item.data(Qt.UserRole)
        if data is None or data[0] != "segment":
            return  # a group header in the grouped-by-code view, not a segment
        _, document_id, start, end, _code_id = data
        self._select_document(document_id)
        cursor = self.viewer.textCursor()
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.KeepAnchor)
        self.viewer.setTextCursor(cursor)
        self.viewer.ensureCursorVisible()

    def _on_segment_list_context_menu(self, pos) -> None:
        if self.conn is None:
            return
        item = self.segment_list.itemAt(pos)
        if item is None:
            return
        data = item.data(Qt.UserRole)
        if data is None:
            return
        if data[0] == "code_header":
            code_id = data[1]
        elif data[0] == "segment":
            code_id = data[4]
        else:
            return

        menu = QMenu(self)
        remove_action = menu.addAction("Remove code from selection in Text Pane")
        chosen = menu.exec(self.segment_list.viewport().mapToGlobal(pos))
        if chosen is remove_action:
            self._remove_code_from_viewer_selection(code_id)

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

    def _on_show_preferences(self) -> None:
        dialog = PreferencesDialog(self._dark_mode, self)
        dialog.darkModeToggled.connect(self.set_dark_mode)
        dialog.exec()

    # -- Testable logic, independent of QFileDialog / QMessageBox ---------

    def set_dark_mode(self, enabled: bool) -> None:
        self._dark_mode = enabled
        self._settings.setValue(DARK_MODE_KEY, enabled)
        self._apply_theme()

    def _apply_theme(self) -> None:
        theme_style = DARK_THEME_STYLE if self._dark_mode else LIGHT_THEME_STYLE
        self.setStyleSheet(theme_style + PANE_FOCUS_STYLE)
        self.viewer.set_theme(self._dark_mode)


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
        self.viewer.exit_insert_mode()
        self.viewer.clear()
        self.viewer.set_code_highlights([])
        self._refresh_documents()
        self._refresh_codes()
        self._update_actions_enabled()
        self.setWindowTitle("OpenAnsho")
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

    def edit_code_description(self, code_id: int, description: str) -> Code:
        if self.conn is None:
            raise RuntimeError("No project open")
        code = db.set_code_description(self.conn, code_id, description or None)
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
        self._recolor_descendants(code_id, color_class, color)
        return code

    def set_code_base_color(self, code_id: int, color_class: str) -> Code:
        if self.conn is None:
            raise RuntimeError("No project open")
        if color_class not in ASSIGNABLE_COLOR_CLASSES:
            raise ValueError(f"Unknown base color class: {color_class}")
        target = db.get_code(self.conn, code_id)
        if target is None:
            raise RuntimeError("Code not found")
        if target.parent_id is not None:
            raise ValueError("Only root codes can be assigned a base color class.")
        code = db.set_code_color(self.conn, code_id, color_class, color_class)
        self._recolor_descendants(code_id, color_class, color_class)
        self._refresh_codes()
        self._refresh_highlights()
        return code

    def _recolor_descendants(self, code_id: int, color_class: str, color: str) -> None:
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

    def delete_code(self, code_id: int) -> None:
        if self.conn is None:
            raise RuntimeError("No project open")
        db.delete_code(self.conn, code_id)
        if self._last_selected_code_id == code_id:
            self._last_selected_code_id = None
        self._refresh_codes()
        self._refresh_highlights()

    def merge_codes(self, keep_id: int, merge_id: int) -> None:
        if self.conn is None:
            raise RuntimeError("No project open")
        if keep_id == merge_id:
            raise ValueError("Cannot merge a code into itself.")
        if self._is_descendant_of(keep_id, merge_id):
            raise ValueError(
                "Cannot keep a code that is nested under the code being merged away."
            )
        db.merge_codes(self.conn, keep_id, merge_id)
        if self._last_selected_code_id == merge_id:
            self._last_selected_code_id = None
        self._refresh_user_filter()
        self._refresh_codes()
        self._refresh_highlights()
        self._render_segments_panel()

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
        self._refresh_user_filter()
        self._refresh_codes()
        self._refresh_highlights()
        self._render_segments_panel()

    def _on_viewer_content_edited(self, position: int, chars_removed: int, chars_added: int) -> None:
        """Persist an insert-mode text edit and reconcile coded segments against it.

        `position`/`chars_removed`/`chars_added` come straight from
        `QTextDocument.contentsChange`: `chars_removed` characters at
        `position` were replaced by `chars_added` new ones. Every segment
        boundary in the document is remapped through the same edit so
        existing codings keep pointing at the same underlying text.
        """
        if self.conn is None or self._current_document_id is None:
            return
        db.update_document_content(
            self.conn, self._current_document_id, self.viewer.toPlainText()
        )
        self._adjust_segments_for_edit(position, chars_removed, chars_added)
        self._refresh_codes()
        self._refresh_highlights()
        self._render_segments_panel()

    def _adjust_segments_for_edit(
        self, position: int, chars_removed: int, chars_added: int
    ) -> None:
        removed_end = position + chars_removed
        delta = chars_added - chars_removed

        def remap(offset: int) -> int:
            if offset <= position:
                return offset
            if offset >= removed_end:
                return offset + delta
            return position  # offset fell inside the replaced span

        for segment in db.list_segments_for_document(self.conn, self._current_document_id):
            new_start = remap(segment.start_offset)
            new_end = remap(segment.end_offset)
            if new_end <= new_start:
                db.delete_segment(self.conn, segment.id)
            elif (new_start, new_end) != (segment.start_offset, segment.end_offset):
                db.update_segment_offsets(self.conn, segment.id, new_start, new_end)

    def _apply_code_to_viewer_selection(self, code_id: int) -> bool:
        cursor = self.viewer.textCursor()
        if not cursor.hasSelection():
            return False
        self.apply_segment(code_id, cursor.selectionStart(), cursor.selectionEnd())
        # Show every code now applied to this span (not just the one just
        # applied), so simultaneously-coding an already-coded segment is
        # visibly additive rather than looking like a replacement.
        self._segments_panel_mode = "cursor"
        self._render_segments_panel()
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
        self._refresh_user_filter()
        self._refresh_codes()
        self._refresh_highlights()
        self._segments_panel_mode = "cursor"
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
        self._refresh_user_filter()
        self._refresh_codes()
        self._refresh_highlights()
        self._segments_panel_mode = "cursor"
        self._render_segments_panel()

    def _remove_code_from_viewer_selection(self, code_id: int) -> None:
        """Delete only `code_id`'s segment(s) touching the viewer's current
        cursor/selection, leaving any other simultaneously-applied codes on
        the same span intact. Used by the Coded Segments pane's right-click
        "Remove code from selection in Text Pane" action."""
        if self.conn is None or self._current_document_id is None:
            return
        matching = [
            segment
            for segment in self._segments_overlapping_viewer_selection()
            if segment.code_id == code_id
        ]
        if not matching:
            return
        for segment in matching:
            db.delete_segment(self.conn, segment.id)
        self._refresh_user_filter()
        self._refresh_codes()
        self._refresh_highlights()
        self._segments_panel_mode = "cursor"
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
        """Segment before/after the cursor, wrapping around the document.

        Only considers segments from the currently selected users, matching
        the highlights/segment list/code counts elsewhere in the Coding pane.
        """
        if self.conn is None or self._current_document_id is None:
            return None
        selected_usernames = self._selected_usernames()
        segments = sorted(
            (
                segment
                for segment in db.list_segments_for_document(self.conn, self._current_document_id)
                if (segment.created_by or "") in selected_usernames
            ),
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
        self._user_filter_overrides = {}
        self.setWindowTitle(f"OpenAnsho — {path.name}")
        self.statusBar().showMessage(str(path))
        self._refresh_documents()
        self._refresh_user_filter()
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

    def _selected_usernames(self) -> set[str]:
        return set(self.user_filter_combo.currentData())

    def _on_user_filter_changed(self) -> None:
        combo = self.user_filter_combo
        self._user_filter_overrides = {
            combo.model().item(i).data(): combo.model().item(i).checkState() == Qt.Checked
            for i in range(combo.model().rowCount())
        }
        self._refresh_codes()
        self._refresh_highlights()
        self._render_segments_panel()

    def _refresh_user_filter(self) -> None:
        """Repopulate the user filter from the project's coded segments.

        Defaults to only the active user (`self.username`) selected; any
        username the user has explicitly checked/unchecked this session
        (`_user_filter_overrides`) keeps that state instead.
        """
        combo = self.user_filter_combo

        if self.conn is None:
            usernames: list[str] = []
        else:
            raw_usernames = db.list_distinct_usernames(self.conn)
            real_names = sorted({name for name in raw_usernames if name})
            has_no_username = any(not name for name in raw_usernames)
            usernames = real_names + ([""] if has_no_username else [])

        active_username = self.username or ""
        combo.blockSignals(True)
        combo.clear()
        for value in usernames:
            label = value if value else NO_USERNAME_TEXT
            checked = self._user_filter_overrides.get(value, value == active_username)
            combo.addItem(label, value, checked=checked)
        combo.blockSignals(False)
        combo.updateText()

    def _filtered_segments_by_code(self, document_id: int | None = None) -> dict[int, int]:
        """Map code_id -> number of segments coded by a currently-selected user."""
        segments = (
            db.list_segments_for_document(self.conn, document_id)
            if document_id is not None
            else db.list_all_segments(self.conn)
        )
        selected = self._selected_usernames()
        counts: dict[int, int] = {}
        for segment in segments:
            if (segment.created_by or "") not in selected:
                continue
            counts[segment.code_id] = counts.get(segment.code_id, 0) + 1
        return counts

    def _refresh_codes(self) -> None:
        previous_current = self.code_tree.currentItem()
        previous_code_id = (
            previous_current.data(0, Qt.UserRole) if previous_current is not None else None
        )

        self.code_tree.clear()
        self.segment_list.clear()
        self._code_items_by_id = {}
        self._new_code_item = None
        if self.conn is None:
            return

        codes = db.list_codes(self.conn)
        children_by_parent: dict[int | None, list[Code]] = {}
        for code in codes:
            children_by_parent.setdefault(code.parent_id, []).append(code)

        current_doc_counts = (
            self._filtered_segments_by_code(self._current_document_id)
            if self._current_document_id is not None
            else {}
        )
        total_counts = self._filtered_segments_by_code()

        sort_key = self._code_sort_key(current_doc_counts, total_counts)
        for children in children_by_parent.values():
            children.sort(key=sort_key)

        def add_children(parent_id: int | None, parent_item: QTreeWidgetItem | None) -> None:
            for code in children_by_parent.get(parent_id, []):
                count_label = f"{current_doc_counts.get(code.id, 0)}/{total_counts.get(code.id, 0)}"
                item = QTreeWidgetItem([code.name, count_label])
                item.setData(0, Qt.UserRole, code.id)
                item.setTextAlignment(1, Qt.AlignRight | Qt.AlignVCenter)
                tooltip = code.description.strip() if code.description else ""
                item.setToolTip(0, tooltip or "(No code description)")
                item.setToolTip(1, tooltip or "(No code description)")
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
        self._update_new_code_placeholder()
        self._sync_matched_code_selection()

    def _refresh_highlights(self) -> None:
        if self.conn is None or self._current_document_id is None:
            self.viewer.set_code_highlights([])
            return
        codes_by_id = {code.id: code for code in db.list_codes(self.conn)}
        selected_usernames = self._selected_usernames()
        segments = [
            segment
            for segment in db.list_segments_for_document(self.conn, self._current_document_id)
            if (segment.created_by or "") in selected_usernames
        ]

        # Selected users each get a fixed horizontal band (alphabetical, first
        # user on top) so their segments stack instead of overlapping when
        # more than one user is selected.
        ordered_usernames = sorted(selected_usernames)
        band_index_by_username = {name: index for index, name in enumerate(ordered_usernames)}
        band_count = max(len(ordered_usernames), 1)

        conflicting_segment_ids = self._overlapping_different_code_segment_ids(segments)

        highlights = []
        for segment in segments:
            code = codes_by_id.get(segment.code_id)
            color = QColor(code.color if code and code.color else "#ffff00")
            color.setAlpha(HIGHLIGHT_ALPHA)

            highlights.append(
                CodeHighlight(
                    start=segment.start_offset,
                    end=segment.end_offset,
                    color=color,
                    band_index=band_index_by_username[segment.created_by or ""],
                    band_count=band_count,
                    outlined=segment.id in conflicting_segment_ids,
                )
            )

        self.viewer.set_code_highlights(highlights)

    @staticmethod
    def _overlapping_different_code_segment_ids(segments: list[db.Segment]) -> set[int]:
        """IDs of segments that overlap another segment coded with a different
        code by a different user — i.e. users disagreeing on how to code a
        span. The same user applying more than one code to the same span is
        simultaneous coding, not a conflict, so it's excluded."""
        conflicting: set[int] = set()
        for i, a in enumerate(segments):
            for b in segments[i + 1 :]:
                if a.code_id == b.code_id:
                    continue
                if (a.created_by or "") == (b.created_by or ""):
                    continue
                if a.start_offset < b.end_offset and b.start_offset < a.end_offset:
                    conflicting.add(a.id)
                    conflicting.add(b.id)
        return conflicting

    def _on_viewer_cursor_moved(self) -> None:
        if len(self._selected_usernames()) > 1:
            self._segments_panel_mode = "cursor"
            self._render_segments_panel()
            return
        if QApplication.focusWidget() is self.viewer:
            selected_usernames = self._selected_usernames()
            segments = [
                segment
                for segment in self._segments_overlapping_viewer_selection()
                if (segment.created_by or "") in selected_usernames
            ]
            if segments:
                self._segments_panel_mode = "cursor"
                self._render_segments_panel()
                return
        item = self.code_tree.currentItem()
        self._show_segments_for_code(item.data(0, Qt.UserRole) if item is not None else None)

    def _show_segments_for_code(self, code_id: int | None) -> None:
        self._segments_panel_mode = "code"
        self._segments_panel_code_id = code_id
        self._render_segments_panel()

    def _segments_overlapping_viewer_selection(self) -> list[db.Segment]:
        """Segments in the current document touching the viewer's cursor/selection."""
        if self.conn is None or self._current_document_id is None:
            return []
        all_segments = db.list_segments_for_document(self.conn, self._current_document_id)
        cursor = self.viewer.textCursor()
        if cursor.hasSelection():
            start, end = cursor.selectionStart(), cursor.selectionEnd()
            return [s for s in all_segments if s.start_offset < end and start < s.end_offset]
        position = cursor.position()
        return [s for s in all_segments if s.start_offset <= position < s.end_offset]

    def _render_segments_panel(self) -> None:
        self.segment_list.clear()
        if self.conn is None:
            self.segment_code_label.clear()
            self.segment_code_label.setStyleSheet("")
            return

        selected_usernames = self._selected_usernames()
        documents_by_id = {doc.id: doc for doc in db.list_documents(self.conn)}

        # Multiple selected users always show the cursor/selection-driven
        # grouped view (comparing everyone's codes at that span); a single
        # user only does when the last panel-affecting action was a viewer
        # cursor/selection move that landed on a coded span (see
        # _on_viewer_cursor_moved) rather than a codebook click.
        if len(selected_usernames) > 1 or self._segments_panel_mode == "cursor":
            self.segment_code_label.clear()
            self.segment_code_label.setStyleSheet("")
            segments = [
                segment
                for segment in self._segments_overlapping_viewer_selection()
                if (segment.created_by or "") in selected_usernames
            ]
            self._render_segments_grouped_by_code(segments, documents_by_id)
            return

        code_id = self._segments_panel_code_id
        code = (
            next((c for c in db.list_codes(self.conn) if c.id == code_id), None)
            if code_id is not None
            else None
        )
        if code is None:
            self.segment_code_label.clear()
            self.segment_code_label.setStyleSheet("")
            return

        self.segment_code_label.setText(code.name)
        self.segment_code_label.setStyleSheet(
            f"background-color: {code.color}; color: {CODE_NAME_TEXT_COLOR.name()}; "
            "border-radius: 3px;"
            if code.color
            else ""
        )

        segments = [
            segment
            for segment in db.list_segments_for_code(self.conn, code_id)
            if (segment.created_by or "") in selected_usernames
        ]
        segments.sort(key=lambda s: s.document_id != self._current_document_id)
        for segment in segments:
            self._add_segment_list_item(segment, documents_by_id, code_id)

    def _render_segments_grouped_by_code(
        self, segments: list[db.Segment], documents_by_id: dict[int, db.Document]
    ) -> None:
        """Show every code applied to `segments`, one colored header per code
        followed by its segments — so codes applied simultaneously to the
        same span (or by different users) are all visible at once, instead
        of only a single code at a time."""
        if not segments:
            return

        codes_by_id = {code.id: code for code in db.list_codes(self.conn)}
        segments_by_code: dict[int, list[db.Segment]] = {}
        for segment in segments:
            segments_by_code.setdefault(segment.code_id, []).append(segment)

        def code_name(code_id: int) -> str:
            code = codes_by_id.get(code_id)
            return code.name if code else "?"

        for code_id in sorted(segments_by_code, key=lambda cid: code_name(cid).lower()):
            code = codes_by_id.get(code_id)
            header_item = QListWidgetItem(code_name(code_id))
            header_item.setFlags(Qt.NoItemFlags)
            header_item.setData(Qt.UserRole, ("code_header", code_id))
            if code and code.color:
                header_item.setBackground(QColor(code.color))
                header_item.setForeground(CODE_NAME_TEXT_COLOR)
            self.segment_list.addItem(header_item)

            group_segments = sorted(
                segments_by_code[code_id], key=lambda s: s.document_id != self._current_document_id
            )
            for segment in group_segments:
                self._add_segment_list_item(segment, documents_by_id, code_id)

    def _add_segment_list_item(
        self, segment: db.Segment, documents_by_id: dict[int, db.Document], code_id: int
    ) -> None:
        doc = documents_by_id.get(segment.document_id)
        doc_name = doc.name if doc else "?"
        username = segment.created_by or NO_USERNAME_TEXT
        full_text = doc.content[segment.start_offset : segment.end_offset] if doc else ""
        snippet = full_text
        if len(snippet) > SNIPPET_MAX_LENGTH:
            snippet = snippet[:SNIPPET_MAX_LENGTH] + "…"

        list_item = QListWidgetItem(f"“{snippet}” [{doc_name}, {username}]")
        list_item.setData(
            Qt.UserRole,
            ("segment", segment.document_id, segment.start_offset, segment.end_offset, code_id),
        )
        list_item.setToolTip(_segment_tooltip(full_text, doc_name, username))
        if segment.document_id != self._current_document_id:
            list_item.setForeground(OTHER_DOCUMENT_TEXT_COLOR)
        self.segment_list.addItem(list_item)

    def _apply_code_filter(self, text: str) -> None:
        query = text.strip().lower()
        for row in range(self.code_tree.topLevelItemCount()):
            item = self.code_tree.topLevelItem(row)
            if item is self._new_code_item:
                continue
            _apply_filter_to_item(item, query)

    def _matching_code_items(self, text: str) -> list[QTreeWidgetItem]:
        """Codes matching `text`; an empty/blank query matches every code."""
        query = text.strip().lower()

        matches: list[QTreeWidgetItem] = []

        def walk(item: QTreeWidgetItem) -> None:
            if item is self._new_code_item:
                return
            if not query or query in item.text(0).lower():
                matches.append(item)
            for row in range(item.childCount()):
                walk(item.child(row))

        for row in range(self.code_tree.topLevelItemCount()):
            walk(self.code_tree.topLevelItem(row))
        return matches

    def _code_name_exists(self, text: str) -> bool:
        lowered = text.lower()
        return any(item.text(0).lower() == lowered for item in self._code_items_by_id.values())

    def _update_new_code_placeholder(self) -> None:
        """Show/hide the "(add new code)" affordance in the code tree.

        It only belongs at the top of the list while the filter field is
        focused, holds non-empty text, and that text isn't an exact match
        for an existing code — otherwise Enter should act on a real code.
        """
        had_placeholder_selected = (
            self._new_code_item is not None
            and self.code_tree.currentItem() is self._new_code_item
        )
        if self._new_code_item is not None:
            index = self.code_tree.indexOfTopLevelItem(self._new_code_item)
            if index != -1:
                self.code_tree.takeTopLevelItem(index)
            self._new_code_item = None

        if self.conn is None or QApplication.focusWidget() is not self.code_filter_input:
            return
        text = self.code_filter_input.text().strip()
        if not text or self._code_name_exists(text):
            return

        item = QTreeWidgetItem([NEW_CODE_LABEL, ""])
        item.setData(0, Qt.UserRole, NEW_CODE_MARKER)
        item.setFlags((item.flags() & ~Qt.ItemIsDragEnabled) & ~Qt.ItemIsDropEnabled)
        font = item.font(0)
        font.setItalic(True)
        item.setFont(0, font)
        item.setForeground(0, OTHER_DOCUMENT_TEXT_COLOR)
        self.code_tree.insertTopLevelItem(0, item)
        self._new_code_item = item
        if had_placeholder_selected:
            self.code_tree.setCurrentItem(item)

    def _current_or_first_match_id(self, matches: list[QTreeWidgetItem]) -> int:
        current = self.code_tree.currentItem()
        if current in matches:
            return current.data(0, Qt.UserRole)
        return matches[0].data(0, Qt.UserRole)

    def _sync_matched_code_selection(self) -> None:
        text = self.code_filter_input.text().strip()
        if not text:
            return
        current = self.code_tree.currentItem()
        if current is not None and current is self._new_code_item:
            return
        matches = self._matching_code_items(text)
        if not matches:
            self.code_tree.setCurrentItem(None)
            return
        if current in matches:
            return
        self.code_tree.setCurrentItem(matches[0])

    def _cycle_matched_code(self, direction: int) -> None:
        matches = self._matching_code_items(self.code_filter_input.text())
        if self._new_code_item is not None:
            matches = [self._new_code_item, *matches]
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
        self._on_viewer_cursor_moved()

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
