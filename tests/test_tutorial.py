from openansho import db, tutorial
from openansho.ui.main_window import TUTORIAL_PROJECT_NAME, MainWindow


def test_tutorial_text_ships_with_the_package():
    text = tutorial.read_tutorial_text()

    assert tutorial.tutorial_text_path().exists()
    assert text.strip()


def test_tutorial_project_holds_only_the_tutorial_documents():
    conn = tutorial.open_tutorial_project()

    documents = db.list_documents(conn)
    assert [doc.name for doc in documents] == list(tutorial.DOCUMENT_NAMES)
    assert documents[0].content == tutorial.read_tutorial_text()
    assert not documents[0].is_pdf
    assert db.list_codes(conn) == []


def test_tutorial_pdf_is_a_pdf_document():
    conn = tutorial.open_tutorial_project()

    pdf = db.get_document_by_name(conn, tutorial.PDF_DOCUMENT_NAME)
    assert pdf is not None
    assert pdf.is_pdf
    assert pdf.source_data == tutorial.tutorial_pdf_path().read_bytes()
    assert pdf.content.strip()


def test_open_tutorial_project_selects_the_introduction(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)

    window.open_tutorial_project()

    assert window.conn is not None
    assert window.document_list.count() == len(tutorial.DOCUMENT_NAMES)
    assert window.document_list.currentItem() is not None
    assert window._current_document_id is not None
    assert window.viewer.toPlainText() == tutorial.read_tutorial_text()


def test_import_is_disabled_in_the_tutorial(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)

    window.open_tutorial_project()

    assert not window.import_action.isEnabled()
    assert "create a new project" in window.import_action.text()

    window.create_project(tmp_path / "real.sqlite")

    assert window.import_action.isEnabled()
    assert "create a new project" not in window.import_action.text()


def test_tutorial_project_is_not_a_file_or_a_recent_project(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    before = window._recent_projects()

    window.open_tutorial_project()

    assert window.project_path is None
    assert window._recent_projects() == before
    assert TUTORIAL_PROJECT_NAME in window.windowTitle()


def test_tutorial_codebook_is_discarded_between_sessions(qtbot):
    first = MainWindow()
    qtbot.addWidget(first)
    first.open_tutorial_project()
    code = first.add_code("instructions")
    first.apply_segment(code.id, 0, 7)
    assert db.list_codes(first.conn)
    first.close_project()

    second = MainWindow()
    qtbot.addWidget(second)
    second.open_tutorial_project()

    assert db.list_codes(second.conn) == []
    assert db.list_all_segments(second.conn) == []


def test_tutorial_coding_works_end_to_end(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    window.open_tutorial_project()

    code = window.add_code("instructions")
    window.apply_segment(code.id, 0, 7)

    segments = db.list_segments_for_document(window.conn, window._current_document_id)
    assert [(s.code_id, s.start_offset, s.end_offset) for s in segments] == [
        (code.id, 0, 7)
    ]
