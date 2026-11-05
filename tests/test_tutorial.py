from PySide6.QtCore import Qt

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
    assert [code.name for code in db.list_codes(conn)] == [
        name for name, _parent in tutorial.TUTORIAL_CODES
    ]


def test_tutorial_pdf_is_a_pdf_document():
    conn = tutorial.open_tutorial_project()

    pdf = db.get_document_by_name(conn, tutorial.PDF_DOCUMENT_NAME)
    assert pdf is not None
    assert pdf.is_pdf
    assert pdf.source_data == tutorial.tutorial_pdf_path().read_bytes()
    assert pdf.content.strip()


def test_tutorial_navigation_is_a_text_document():
    conn = tutorial.open_tutorial_project()

    doc = db.get_document_by_name(conn, tutorial.NAVIGATION_DOCUMENT_NAME)
    assert doc is not None
    assert not doc.is_pdf
    assert doc.content == tutorial.tutorial_file_path(
        tutorial.NAVIGATION_DOCUMENT_NAME
    ).read_text(encoding="utf-8")


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

    names = [code.name for code in db.list_codes(second.conn)]
    assert "instructions" not in names
    assert names == [name for name, _parent in tutorial.TUTORIAL_CODES]
    assert {s.created_by for s in db.list_all_segments(second.conn)} == {
        tutorial.TUTORIAL_USERNAME
    }


def test_tutorial_coding_works_end_to_end(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    window.open_tutorial_project()

    code = window.add_code("instructions")
    window.apply_segment(code.id, 0, 7)

    segments = db.list_segments_for_document(window.conn, window._current_document_id)
    assert [
        (s.code_id, s.start_offset, s.end_offset)
        for s in segments
        if s.created_by != tutorial.TUTORIAL_USERNAME
    ] == [(code.id, 0, 7)]


def _codes_by_name(conn):
    return {code.name: code for code in db.list_codes(conn)}


def test_tutorial_coder_codes_the_tutorials_prompts():
    conn = tutorial.open_tutorial_project()
    codes = _codes_by_name(conn)
    documents = db.list_documents(conn)

    coded = [
        (doc.name, doc.content[s.start_offset : s.end_offset], s.code_id, s.created_by)
        for doc in documents
        for s in db.list_segments_for_document(conn, doc.id)
    ]
    assert coded == [
        (document_name, passage, codes[code_name].id, tutorial.TUTORIAL_USERNAME)
        for document_name, passage, code_name in tutorial.TUTORIAL_SEGMENTS
    ]
    # Only the introduction and 03 Codebook come pre-coded.
    assert {name for name, *_ in coded} == {
        tutorial.DOCUMENT_NAME,
        tutorial.CODEBOOK_DOCUMENT_NAME,
    }


def test_tutorial_segments_cover_each_prompt_once():
    """Every passage is the inside of one "(...)" prompt, and a repeated
    prompt is coded at successive occurrences rather than the first again."""
    conn = tutorial.open_tutorial_project()
    content = {doc.name: doc.content for doc in db.list_documents(conn)}

    located = tutorial.tutorial_segment_offsets(content)

    for name, start, end, _code in located:
        assert content[name][start - 1] == "("
        assert content[name][end] == ")"
    assert len({(name, start) for name, start, *_ in located}) == len(located)
    for name in {name for name, *_ in tutorial.TUTORIAL_SEGMENTS}:
        for passage in {p for n, p, _c in tutorial.TUTORIAL_SEGMENTS if n == name}:
            listed = sum(
                1 for n, p, _c in tutorial.TUTORIAL_SEGMENTS if (n, p) == (name, passage)
            )
            assert content[name].count(f"({passage})") == listed


def test_tutorial_codebook_document_is_a_text_document():
    conn = tutorial.open_tutorial_project()

    doc = db.get_document_by_name(conn, tutorial.CODEBOOK_DOCUMENT_NAME)
    assert doc is not None
    assert not doc.is_pdf
    assert doc.content == tutorial.tutorial_file_path(
        tutorial.CODEBOOK_DOCUMENT_NAME
    ).read_text(encoding="utf-8")


def test_tutorial_codebook_mirrors_the_introductions_structure():
    conn = tutorial.open_tutorial_project()
    codes = _codes_by_name(conn)
    by_id = {code.id: code for code in codes.values()}

    parents = {
        code.name: by_id[code.parent_id].name if code.parent_id else None
        for code in codes.values()
    }
    assert parents == dict(tutorial.TUTORIAL_CODES)


# Everything the tutorial documents have the user type into the code filter.
TUTORIAL_TYPED_NAMES = (
    "code", "instructions", "ins", "selection", "explanations", "general",
    "shortcuts", "action", "call", "test", "test1", "test2", "c",
)


def test_tutorial_code_names_never_match_what_the_tutorials_ask_for():
    for name, _parent in tutorial.TUTORIAL_CODES:
        for typed in TUTORIAL_TYPED_NAMES:
            assert typed not in name.lower(), (name, typed)


def _user_filter_states(window):
    model = window.user_filter_combo.model()
    return {
        model.item(i).data(): model.item(i).checkState() == Qt.Checked
        for i in range(model.rowCount())
    }


def _set_user_checked(window, value, checked):
    model = window.user_filter_combo.model()
    for i in range(model.rowCount()):
        if model.item(i).data() == value:
            model.item(i).setCheckState(Qt.Checked if checked else Qt.Unchecked)
            return
    raise AssertionError(f"no user filter entry {value!r}")


def test_tutorial_coder_is_hidden_until_enabled_in_the_user_filter(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    window.open_tutorial_project()
    window.username = "alice"
    window._apply_active_user_default_filter()
    to_do = _codes_by_name(window.conn)["To Do"]

    assert _user_filter_states(window) == {tutorial.TUTORIAL_USERNAME: False}
    assert window._code_items_by_id[to_do.id].text(1) == "0/0"
    assert window.viewer._code_highlights == []

    _set_user_checked(window, tutorial.TUTORIAL_USERNAME, True)

    assert window._code_items_by_id[to_do.id].text(1) == "2/2"
    highlighted = {(h.start, h.end) for h in window.viewer._code_highlights}
    expected = {
        (s.start_offset, s.end_offset)
        for s in db.list_segments_for_document(
            window.conn, window._current_document_id
        )
    }
    assert highlighted == expected


def test_tutorial_codes_are_colored_like_any_other(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    window.open_tutorial_project()

    codes = _codes_by_name(window.conn)
    assert all(code.color and code.color_class for code in codes.values())
    assert codes["Highlight"].color_class == codes["To Do"].color_class
    assert codes["Highlight"].color != codes["To Do"].color
