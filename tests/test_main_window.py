from PySide6.QtCore import QSettings
from PySide6.QtGui import QPalette

from openansho import __version__, db
from openansho.ui import main_window as main_window_module
from openansho.ui.main_window import (
    DARK_MODE_KEY,
    SETTINGS_APPLICATION,
    SETTINGS_ORGANIZATION,
    MainWindow,
)


def test_new_window_has_import_disabled(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)

    assert window.conn is None
    assert not window.import_action.isEnabled()


def test_create_project_enables_import_and_sets_title(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)

    project_path = tmp_path / "my_study.sqlite"
    window.create_project(project_path)

    assert window.conn is not None
    assert window.import_action.isEnabled()
    assert "my_study.sqlite" in window.windowTitle()
    assert project_path.exists()


def test_window_title_shows_version(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)

    assert window.windowTitle() == f"OpenAnsho {__version__}"

    window.create_project(tmp_path / "my_study.sqlite")

    assert window.windowTitle().startswith(f"OpenAnsho {__version__} — ")


def test_import_document_populates_list_and_viewer(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.create_project(tmp_path / "project.sqlite")

    doc_path = tmp_path / "interview_01.txt"
    doc_path.write_text("Hello world.", encoding="utf-8")
    window.import_document(doc_path)

    assert window.document_list.count() == 1
    assert window.document_list.item(0).text() == "interview_01.txt"
    assert window.viewer.toPlainText() == "Hello world."


def test_import_document_duplicate_name_aborts_without_overwrite(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.create_project(tmp_path / "project.sqlite")

    doc_path = tmp_path / "interview_01.txt"
    doc_path.write_text("Original content.", encoding="utf-8")
    window.import_document(doc_path)

    doc_path.write_text("Changed content.", encoding="utf-8")
    result = window.import_document(doc_path)

    assert result is False
    assert window.document_list.count() == 1
    assert db.get_document(window.conn, 1).content == "Original content."


def test_import_document_duplicate_name_overwrite_replaces_content(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.create_project(tmp_path / "project.sqlite")

    doc_path = tmp_path / "interview_01.txt"
    doc_path.write_text("Original content.", encoding="utf-8")
    window.import_document(doc_path)

    doc_path.write_text("Changed content.", encoding="utf-8")
    result = window.import_document(doc_path, overwrite=True)

    assert result is True
    assert window.document_list.count() == 1
    assert window.viewer.toPlainText() == "Changed content."


def test_open_existing_project_loads_documents(qtbot, tmp_path):
    project_path = tmp_path / "existing.sqlite"
    conn = db.connect(project_path)
    db.create_document(conn, "already_here.txt", "Existing content.")
    conn.close()

    window = MainWindow()
    qtbot.addWidget(window)
    window.open_project(project_path)

    assert window.document_list.count() == 1
    assert window.document_list.item(0).text() == "already_here.txt"


def test_selecting_document_updates_viewer(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.create_project(tmp_path / "project.sqlite")

    (tmp_path / "a.txt").write_text("Content A", encoding="utf-8")
    (tmp_path / "b.txt").write_text("Content B", encoding="utf-8")
    window.import_document(tmp_path / "a.txt")
    window.import_document(tmp_path / "b.txt")

    window.document_list.setCurrentRow(0)
    assert window.viewer.toPlainText() == "Content A"

    window.document_list.setCurrentRow(1)
    assert window.viewer.toPlainText() == "Content B"


def test_dark_mode_at_startup_keeps_visual_selection_visible(qtbot, tmp_path, monkeypatch):
    """Regression test: when the OS is already in Dark Mode at launch (so the
    window opens straight into dark mode, with no explicit toggle), the
    viewer's native text-selection highlight used to end up the same color
    as ordinary text once the window was first shown, making a visual-mode
    selection invisible. See VimTextViewer.set_theme.
    """
    monkeypatch.setattr(main_window_module, "detect_dark_mode", lambda: True)
    settings = QSettings(SETTINGS_ORGANIZATION, SETTINGS_APPLICATION)
    settings.remove(DARK_MODE_KEY)

    window = MainWindow()
    qtbot.addWidget(window)
    window.create_project(tmp_path / "project.sqlite")
    doc_path = tmp_path / "doc.txt"
    doc_path.write_text("hello world", encoding="utf-8")
    window.import_document(doc_path)

    window.show()
    window.document_list.setCurrentRow(0)
    # The bug only manifests once the stylesheet's deferred repolish is
    # actually delivered through the event loop, which a bare .show() does
    # not force by itself.
    qtbot.wait(100)

    palette = window.viewer.palette()
    assert palette.color(QPalette.Highlight) != palette.color(QPalette.Base)
    assert palette.color(QPalette.HighlightedText) != palette.color(QPalette.Text)

    settings.remove(DARK_MODE_KEY)


def _project_with_two_coded_documents(window, tmp_path):
    window.create_project(tmp_path / "project.sqlite")
    (tmp_path / "a.txt").write_text("alpha text", encoding="utf-8")
    (tmp_path / "b.txt").write_text("beta text", encoding="utf-8")
    window.import_document(tmp_path / "a.txt")
    doc_a = db.get_document_by_name(window.conn, "a.txt")
    window.import_document(tmp_path / "b.txt")
    doc_b = db.get_document_by_name(window.conn, "b.txt")
    parent = window.add_code("Parent")
    child = window.add_code("Only in A", parent_id=parent.id)
    db.create_segment(window.conn, doc_a.id, child.id, 0, 5)
    db.create_segment(window.conn, doc_b.id, parent.id, 0, 4)
    return doc_a, doc_b, parent, child


def test_delete_document_removes_its_segments_but_keeps_codes(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    doc_a, doc_b, parent, child = _project_with_two_coded_documents(window, tmp_path)
    codes_before = {(c.id, c.name, c.parent_id) for c in db.list_codes(window.conn)}

    window.delete_document(doc_a.id)

    assert db.get_document(window.conn, doc_a.id) is None
    assert db.list_segments_for_document(window.conn, doc_a.id) == []
    assert len(db.list_segments_for_document(window.conn, doc_b.id)) == 1
    assert {(c.id, c.name, c.parent_id) for c in db.list_codes(window.conn)} == codes_before
    assert [window.document_list.item(i).text() for i in range(window.document_list.count())] == [
        "b.txt"
    ]


def test_delete_other_document_keeps_current_document_open(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    doc_a, doc_b, _parent, _child = _project_with_two_coded_documents(window, tmp_path)
    assert window._current_document_id == doc_b.id

    window.delete_document(doc_a.id)

    assert window._current_document_id == doc_b.id
    assert window.viewer.toPlainText() == "beta text"


def test_delete_current_document_clears_viewer(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    _doc_a, doc_b, _parent, _child = _project_with_two_coded_documents(window, tmp_path)

    window.delete_document(doc_b.id)

    assert window._current_document_id is None
    assert window.viewer.toPlainText() == ""


def test_document_context_menu_deletes_after_confirmation(qtbot, tmp_path, monkeypatch):
    window = MainWindow()
    qtbot.addWidget(window)
    doc_a, _doc_b, _parent, _child = _project_with_two_coded_documents(window, tmp_path)

    def fake_exec(_self, menu, _global_pos):
        return next(a for a in menu.actions() if a.text() == "Delete…")

    monkeypatch.setattr(MainWindow, "_exec_context_menu", fake_exec)
    monkeypatch.setattr(MainWindow, "_confirm_delete_document", lambda _self, _name: True)
    item = window.document_list.item(0)
    window._on_document_context_menu(window.document_list.visualItemRect(item).center())

    assert db.get_document(window.conn, doc_a.id) is None


def test_document_context_menu_keeps_document_when_cancelled(qtbot, tmp_path, monkeypatch):
    window = MainWindow()
    qtbot.addWidget(window)
    doc_a, _doc_b, _parent, _child = _project_with_two_coded_documents(window, tmp_path)

    def fake_exec(_self, menu, _global_pos):
        return next(a for a in menu.actions() if a.text() == "Delete…")

    monkeypatch.setattr(MainWindow, "_exec_context_menu", fake_exec)
    monkeypatch.setattr(MainWindow, "_confirm_delete_document", lambda _self, _name: False)
    item = window.document_list.item(0)
    window._on_document_context_menu(window.document_list.visualItemRect(item).center())

    assert db.get_document(window.conn, doc_a.id) is not None
