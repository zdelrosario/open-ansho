import zipfile
from pathlib import Path

import pytest

from openansho import text_extract
from openansho.text_extract import DocumentReadError
from openansho.ui.main_window import MainWindow

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'

CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""


def paragraph(*runs: str) -> str:
    """A `w:p` whose runs are the given XML fragments (or plain text)."""
    body = "".join(r if r.startswith("<") else f"<w:r><w:t>{r}</w:t></w:r>" for r in runs)
    return f"<w:p>{body}</w:p>"


def write_docx(path: Path, body: str) -> Path:
    """Write a minimal .docx whose `w:body` contains `body`."""
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f"<w:document {W}><w:body>{body}</w:body></w:document>"
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", CONTENT_TYPES)
        archive.writestr("word/document.xml", document)
    return path


def test_paragraphs_become_lines(tmp_path):
    path = write_docx(
        tmp_path / "notes.docx",
        paragraph("First paragraph.") + paragraph("Second paragraph."),
    )

    assert text_extract.read_docx_text(path) == "First paragraph.\nSecond paragraph."


def test_runs_within_a_paragraph_are_joined_without_separators(tmp_path):
    path = write_docx(tmp_path / "split.docx", paragraph("Hel", "lo ", "world."))

    assert text_extract.read_docx_text(path) == "Hello world."


def test_empty_paragraph_becomes_a_blank_line(tmp_path):
    path = write_docx(
        tmp_path / "spaced.docx",
        paragraph("Before.") + "<w:p/>" + paragraph("After."),
    )

    assert text_extract.read_docx_text(path) == "Before.\n\nAfter."


def test_tabs_and_breaks_are_preserved(tmp_path):
    path = write_docx(
        tmp_path / "whitespace.docx",
        paragraph(
            "<w:r><w:t>A</w:t><w:tab/><w:t>B</w:t><w:br/><w:t>C</w:t></w:r>"
        ),
    )

    assert text_extract.read_docx_text(path) == "A\tB\nC"


def test_table_cell_paragraphs_are_read_in_document_order(tmp_path):
    table = (
        "<w:tbl><w:tr>"
        f"<w:tc>{paragraph('Cell one')}</w:tc>"
        f"<w:tc>{paragraph('Cell two')}</w:tc>"
        "</w:tr></w:tbl>"
    )
    path = write_docx(tmp_path / "table.docx", paragraph("Intro.") + table)

    assert text_extract.read_docx_text(path) == "Intro.\nCell one\nCell two"


def test_field_instructions_and_tracked_deletions_are_skipped(tmp_path):
    path = write_docx(
        tmp_path / "revised.docx",
        paragraph(
            "<w:r><w:instrText> PAGE </w:instrText></w:r>",
            "<w:del><w:r><w:delText>removed </w:delText></w:r></w:del>",
            "kept",
        ),
    )

    assert text_extract.read_docx_text(path) == "kept"


def test_non_docx_file_with_docx_extension_reports_a_clear_error(tmp_path):
    path = tmp_path / "fake.docx"
    path.write_text("not a zip archive", encoding="utf-8")

    with pytest.raises(DocumentReadError, match="not a valid Word document"):
        text_extract.read_docx_text(path)


def test_zip_without_document_part_reports_a_clear_error(tmp_path):
    path = tmp_path / "empty.docx"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", CONTENT_TYPES)

    with pytest.raises(DocumentReadError, match="word/document.xml"):
        text_extract.read_docx_text(path)


def test_legacy_doc_extension_is_rejected_with_guidance(tmp_path):
    path = tmp_path / "old.doc"
    path.write_bytes(b"\xd0\xcf\x11\xe0")

    with pytest.raises(DocumentReadError, match="save it as .docx"):
        text_extract.read_document_text(path)


def test_plain_text_still_reads_as_utf8(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("Plain café text.", encoding="utf-8")

    assert text_extract.read_document_text(path) == "Plain café text."


def test_non_utf8_text_reports_a_clear_error(tmp_path):
    path = tmp_path / "latin1.txt"
    path.write_bytes("café".encode("latin-1"))

    with pytest.raises(DocumentReadError, match="UTF-8"):
        text_extract.read_document_text(path)


def test_import_document_accepts_a_docx(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.create_project(tmp_path / "project.sqlite")

    doc_path = write_docx(
        tmp_path / "interview_01.docx",
        paragraph("Interviewer: How did that go?") + paragraph("Participant: Well."),
    )
    assert window.import_document(doc_path)

    assert window.document_list.item(0).text() == "interview_01.docx"
    assert window.viewer.toPlainText() == (
        "Interviewer: How did that go?\nParticipant: Well."
    )


def test_import_document_rejects_an_unreadable_docx(qtbot, tmp_path, monkeypatch):
    window = MainWindow()
    qtbot.addWidget(window)
    window.create_project(tmp_path / "project.sqlite")

    warnings = []
    monkeypatch.setattr(
        "openansho.ui.main_window.QMessageBox.warning",
        lambda *args: warnings.append(args[2]),
    )
    doc_path = tmp_path / "broken.docx"
    doc_path.write_text("not a zip archive", encoding="utf-8")

    assert not window.import_document(doc_path)
    assert window.document_list.count() == 0
    assert "not a valid Word document" in warnings[0]
