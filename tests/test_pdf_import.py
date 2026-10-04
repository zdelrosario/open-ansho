import pytest

from openansho import db, pdf_extract, text_extract
from openansho.text_extract import DocumentReadError
from openansho.ui.main_window import MainWindow


def _open_project(window, tmp_path):
    window.create_project(tmp_path / "project.sqlite")


def _import_pdf(window, tmp_path, write_pdf, pages, name="report.pdf"):
    path = write_pdf(tmp_path / name, pages)
    window.import_document(path)
    window.document_list.setCurrentRow(window.document_list.count() - 1)
    return path


# -- extraction ---------------------------------------------------------------


def test_pdf_text_is_extracted_with_pages_separated_by_form_feed(tmp_path, write_pdf):
    path = write_pdf(tmp_path / "two.pdf", [["First page."], ["Second page."]])

    assert text_extract.read_document_text(path) == "First page.\n\f\nSecond page.\n"


def test_lines_within_a_page_are_kept(tmp_path, write_pdf):
    path = write_pdf(tmp_path / "lines.pdf", [["One.", "Two.", "Three."]])

    assert text_extract.read_document_text(path) == "One.\nTwo.\nThree.\n"


def test_a_file_that_is_not_a_pdf_reports_a_readable_error(tmp_path):
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"not a pdf at all")

    with pytest.raises(DocumentReadError) as excinfo:
        text_extract.read_document_text(path)

    assert "broken.pdf" in str(excinfo.value)


def test_page_ranges_cover_each_pages_text():
    """A page's range is exactly its text: the separator belongs to neither."""
    content = "one\n\f\ntwo\n\f\nthree"

    assert [content[start:end] for start, end in pdf_extract.page_ranges(content)] == [
        "one\n",
        "two\n",
        "three",
    ]


def test_a_document_without_separators_is_a_single_page():
    assert pdf_extract.page_ranges("plain text") == [(0, 10)]
    assert pdf_extract.page_for_offset("plain text", 7) == 0


@pytest.mark.parametrize(
    "offset, expected_page",
    [(0, 0), (3, 0), (4, 0), (6, 1), (9, 1), (11, 2)],
)
def test_page_for_offset(offset, expected_page):
    # "one\n" | \f\n | "two\n" | \f\n | "x"
    content = "one\n\f\ntwo\n\f\nx"

    assert pdf_extract.page_for_offset(content, offset) == expected_page


def test_a_character_is_only_ever_as_tall_as_its_own_line(tmp_path, write_pdf):
    """Regression: a page whose text does not come out top-to-bottom.

    A real journal page emits its margin line numbers after its footer, so
    the extraction order jumps back *up* the page. Grouping characters into
    lines by which way that order moves merged the two, and every character
    in the merged run ended up as tall as the gap between them — so putting
    the cursor on one covered half the page.
    """
    path = write_pdf(
        tmp_path / "journal.pdf",
        [["Body line one.", "Body line two."]],
        strays=[[(50, 47, "footer line here"), (300, 577, "5")]],
    )
    source = pdf_extract.PdfPageSource(path.read_bytes())

    heights = [
        box.height() for line in source.page_lines(0) for box in line.boxes
    ]

    assert len(source.page_lines(0)) == 4  # the stray is its own line
    assert max(heights) < 3 * min(heights)


def test_characters_on_one_line_are_leveled_to_a_common_height(tmp_path, write_pdf):
    path = write_pdf(tmp_path / "lines.pdf", [["Agile pygmy."]])
    source = pdf_extract.PdfPageSource(path.read_bytes())

    # Capitals, x-height letters and descenders all sit in the same band.
    rects = [
        source.char_rect(0, index)
        for index in range(len(source.raw_page_text(0)))
        if source.char_rect(0, index) is not None
    ]
    assert len(rects) > 5
    assert len({round(rect.top()) for rect in rects}) == 1
    assert len({round(rect.height()) for rect in rects}) == 1


# -- import -------------------------------------------------------------------


def test_importing_a_pdf_stores_its_kind_and_its_bytes(qtbot, tmp_path, write_pdf):
    window = MainWindow()
    qtbot.addWidget(window)
    _open_project(window, tmp_path)

    path = _import_pdf(window, tmp_path, write_pdf, [["Hello."]])

    doc = db.list_documents(window.conn)[0]
    assert doc.kind == db.DOCUMENT_KIND_PDF
    assert doc.is_pdf
    assert doc.source_data == path.read_bytes()
    assert doc.content == "Hello.\n"


def test_importing_a_text_document_stores_no_source_bytes(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    _open_project(window, tmp_path)
    path = tmp_path / "notes.txt"
    path.write_text("Plain.", encoding="utf-8")

    window.import_document(path)

    doc = db.list_documents(window.conn)[0]
    assert doc.kind == db.DOCUMENT_KIND_TEXT
    assert not doc.is_pdf
    assert doc.source_data is None


def test_documents_from_a_project_predating_pdf_support_still_load(tmp_path):
    """The kind/source_data columns are added by migration, so they come back
    as NULL for a document inserted before they existed."""
    path = tmp_path / "old.sqlite"
    conn = db.connect(path)
    conn.execute("DROP TABLE documents")
    conn.execute(
        "CREATE TABLE documents (id INTEGER PRIMARY KEY, name TEXT NOT NULL, "
        "content TEXT NOT NULL, created_at TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT INTO documents (name, content, created_at) VALUES ('a.txt', 'Hi', 'now')"
    )
    conn.commit()
    conn.close()

    reopened = db.connect(path)
    doc = db.list_documents(reopened)[0]

    assert doc.kind is None
    assert not doc.is_pdf
    assert doc.content == "Hi"


# -- the page pane ------------------------------------------------------------


def test_the_page_pane_is_up_only_for_pdf_documents(qtbot, tmp_path, write_pdf):
    window = MainWindow()
    qtbot.addWidget(window)
    _open_project(window, tmp_path)
    text_path = tmp_path / "notes.txt"
    text_path.write_text("Plain.", encoding="utf-8")
    window.import_document(text_path)
    _import_pdf(window, tmp_path, write_pdf, [["Hello."]])

    assert window.viewer_stack.currentWidget() is window.pdf_pane
    assert window.pdf_viewer.page_count == 1

    window.document_list.setCurrentRow(0)  # back to the text document

    assert window.viewer_stack.currentWidget() is window.viewer
    assert window.pdf_viewer.page_count == 0


def test_closing_the_project_puts_the_text_pane_back(qtbot, tmp_path, write_pdf):
    window = MainWindow()
    qtbot.addWidget(window)
    _open_project(window, tmp_path)
    _import_pdf(window, tmp_path, write_pdf, [["Hello."]])

    window.close_project()

    assert window.viewer_stack.currentWidget() is window.viewer
    assert window.pdf_viewer.page_count == 0


def test_a_pdf_reopened_from_the_project_file_renders_without_the_original(
    qtbot, tmp_path, write_pdf
):
    window = MainWindow()
    qtbot.addWidget(window)
    project = tmp_path / "project.sqlite"
    window.create_project(project)
    path = _import_pdf(window, tmp_path, write_pdf, [["Hello."], ["Bye."]])
    path.unlink()

    window.open_project(project)
    window.document_list.setCurrentRow(0)

    assert window.pdf_viewer.page_count == 2


def test_every_page_is_laid_out_at_once(qtbot, tmp_path, write_pdf):
    """Pages scroll continuously, so there is no current page to turn to."""
    window = MainWindow()
    qtbot.addWidget(window)
    _open_project(window, tmp_path)
    _import_pdf(window, tmp_path, write_pdf, [["First."], ["Second."], ["Third."]])

    viewer = window.pdf_viewer
    assert viewer.page_count == 3
    tops = [viewer.page_rect(page).top() for page in range(3)]
    assert tops == sorted(tops)
    assert len(set(tops)) == 3
