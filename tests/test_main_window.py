from opencoder import db
from opencoder.ui.main_window import MainWindow


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
