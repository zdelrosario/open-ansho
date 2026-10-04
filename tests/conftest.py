import os

# Creating and tearing down ~140 real on-screen windows in quick succession
# crashes/segfaults the native Cocoa platform plugin on macOS. Tests don't
# need a visible window, so default to the offscreen QPA platform; this must
# run before pytest-qt's session-scoped `qapp` fixture constructs the
# QApplication. Explicitly set QT_QPA_PLATFORM beforehand to override.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from openansho import user


# A minimal hand-written PDF, the same move `tests/test_docx_import.py` makes
# for .docx. Painting one with QPdfWriter instead would depend on the machine
# having fonts installed: a bare Windows CI runner has none, QPainter draws no
# glyphs, and every page comes back with empty text. Writing the file directly
# with /Helvetica — one of the 14 fonts every PDF reader supplies itself —
# makes the extracted text identical everywhere.
PDF_PAGE_WIDTH = 612
PDF_PAGE_HEIGHT = 792
PDF_FONT_SIZE = 12
PDF_LINE_HEIGHT = 20
PDF_TEXT_LEFT = 50
PDF_TEXT_TOP = 742  # in PDF user space, measured up from the bottom edge
# The figure each page carries, as (x, y, width, height) in the same space —
# the sort of non-text area a region gets drawn over.
PDF_FIGURE_BOX = (50, 400, 300, 160)


def _pdf_bytes(pages):
    font_number = 3
    page_numbers = [4 + 2 * index for index in range(len(pages))]
    content_numbers = [5 + 2 * index for index in range(len(pages))]

    objects = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: (
            "<< /Type /Pages /Kids [%s] /Count %d >>"
            % (" ".join(f"{n} 0 R" for n in page_numbers), len(pages))
        ).encode(),
        font_number: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    }

    for index, lines in enumerate(pages):
        objects[page_numbers[index]] = (
            f"<< /Type /Page /Parent 2 0 R "
            f"/MediaBox [0 0 {PDF_PAGE_WIDTH} {PDF_PAGE_HEIGHT}] "
            f"/Resources << /Font << /F1 {font_number} 0 R >> >> "
            f"/Contents {content_numbers[index]} 0 R >>"
        ).encode()

        parts = []
        if lines:
            parts.append(
                f"BT /F1 {PDF_FONT_SIZE} Tf {PDF_TEXT_LEFT} {PDF_TEXT_TOP} Td "
                f"{PDF_LINE_HEIGHT} TL"
            )
            for line_index, line in enumerate(lines):
                text = line.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
                parts.append(f"({text}) Tj" if line_index == 0 else f"T* ({text}) Tj")
            parts.append("ET")
        x, y, width, height = PDF_FIGURE_BOX
        parts.append(f"0.27 0.51 0.71 rg {x} {y} {width} {height} re f")
        stream = ("\n".join(parts) + "\n").encode()
        objects[content_numbers[index]] = (
            f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"endstream"
        )

    out = bytearray(b"%PDF-1.4\n")
    offsets = {}
    for number in sorted(objects):
        offsets[number] = len(out)
        out += f"{number} 0 obj\n".encode() + objects[number] + b"\nendobj\n"

    xref_at = len(out)
    last = max(objects)
    out += f"xref\n0 {last + 1}\n".encode() + b"0000000000 65535 f \n"
    for number in range(1, last + 1):
        out += f"{offsets[number]:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {last + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_at}\n%%EOF\n"
    ).encode()
    return bytes(out)


@pytest.fixture
def write_pdf():
    """Factory writing a small real PDF: `write_pdf(path, [["line"], ...])`.

    One list of text lines per page; every page also carries a filled
    rectangle standing in for a figure.
    """

    def _write_pdf(path, pages):
        path.write_bytes(_pdf_bytes(pages))
        return path

    return _write_pdf


@pytest.fixture(autouse=True)
def _isolate_username_file(tmp_path, monkeypatch):
    """The real .openansho_user sidecar lives next to the installed app, one
    per machine — redirect it into each test's own tmp_path so tests never
    read or clobber the developer's actual username file on disk. The
    site-packages branch is pinned off as well, so a test run against an
    installed copy of the package stays inside tmp_path too."""
    monkeypatch.setattr(user, "application_directory", lambda: tmp_path)
    monkeypatch.setattr(user, "installed_in_site_packages", lambda: False)
