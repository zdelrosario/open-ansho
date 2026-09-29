"""Read and render PDF documents.

A PDF is imported the same way as any other document: its text is extracted
into `documents.content`, so every existing coding, navigation and reporting
path works on it unchanged. Two conventions make the flat text addressable
back to the original pages:

- Pages are separated in the content by `PAGE_SEPARATOR` (a form feed, the
  usual convention for page breaks in extracted text). Page boundaries are
  therefore derived from the content itself rather than stored alongside it,
  which keeps them correct after the text is edited in insert mode.
- Each coded rectangular region of a page contributes one `REGION_MARKER`
  character, on its own line at the end of that page's text. A region is
  coded by coding that single character, which is also what makes the vim
  motions treat an image as one character.

Unlike `db.py`/`reporting.py`/`text_extract.py` this module does import Qt —
rendering a PDF page means using Qt's PDF engine, there being no other
renderer in the dependency list. It needs no QApplication, though (not even
for `render`), so it stays usable from tests and a future CLI, which is what
the no-Qt rule in the other non-UI modules is really protecting.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QBuffer, QIODevice, QSize, QSizeF
from PySide6.QtGui import QImage
from PySide6.QtPdf import QPdfDocument

from openansho.text_extract import DocumentReadError

PAGE_SEPARATOR = "\f"

# U+25AD WHITE RECTANGLE: one character standing in for one coded region of a
# page, picked to be visible in the text pane (unlike U+FFFC OBJECT
# REPLACEMENT CHARACTER, which has no glyph in the default UI font and so no
# width to highlight) and to look like what it represents.
REGION_MARKER = "▭"
REGION_MARKER_LINE = REGION_MARKER + "\n"


def read_pdf_text(path: Path) -> str:
    """Extract `path`'s text, pages separated by `PAGE_SEPARATOR`."""
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise DocumentReadError(f"Could not read {path.name}: {exc}") from None
    return pdf_text(data, path.name)


def pdf_text(data: bytes, name: str) -> str:
    """Extract the text of the PDF held in `data`; `name` names it in errors.

    The result always ends with a newline, which — together with the newline
    the separator carries — means every page's text ends with one. That's
    what lets a region marker be appended to a page as its own line (see
    `region_marker_position`) without gluing itself onto the last line of
    text on the page.
    """
    source = PdfPageSource(data, name)
    pages = [source.page_text(page) for page in range(source.page_count)]
    return f"\n{PAGE_SEPARATOR}\n".join(pages) + "\n"


class PdfPageSource:
    """A loaded PDF, for extracting page text and rendering page images.

    Constructed from the bytes stored in `documents.source_data` rather than
    from a path, so a project file keeps working after the imported file is
    moved or deleted.
    """

    def __init__(self, data: bytes, name: str = "the document") -> None:
        self._buffer = QBuffer()
        # setData copies into the buffer's own storage; the QBuffer has to
        # outlive the QPdfDocument reading through it, hence holding onto it.
        self._buffer.setData(data)
        self._buffer.open(QIODevice.ReadOnly)
        self._document = QPdfDocument()
        self._document.load(self._buffer)
        status = self._document.status()
        if status != QPdfDocument.Status.Ready:
            if self._document.error() == QPdfDocument.Error.IncorrectPassword:
                raise DocumentReadError(
                    f"{name} is password-protected. Remove the password and import it again."
                )
            raise DocumentReadError(f"Could not read {name} as a PDF.")

    @property
    def page_count(self) -> int:
        return self._document.pageCount()

    def page_text(self, page: int) -> str:
        """One page's text, newline-normalized and without trailing blank space."""
        raw = self._document.getAllText(page).text()
        return raw.replace("\r\n", "\n").replace("\r", "\n").rstrip()

    def page_size(self, page: int) -> QSizeF:
        return self._document.pagePointSize(page)

    def render(self, page: int, size: QSize) -> QImage:
        return self._document.render(page, size)


def page_ranges(content: str) -> list[tuple[int, int]]:
    """Character range of each page's text in `content`, one pair per page.

    Ranges exclude the `PAGE_SEPARATOR` characters between them, so page
    `n`'s text is `content[start:end]`.
    """
    ranges = []
    start = 0
    while True:
        separator = content.find(PAGE_SEPARATOR, start)
        if separator == -1:
            ranges.append((start, len(content)))
            return ranges
        ranges.append((start, separator))
        start = separator + len(PAGE_SEPARATOR)


def page_count_in_text(content: str) -> int:
    return content.count(PAGE_SEPARATOR) + 1


def page_for_offset(content: str, offset: int) -> int:
    """Index of the page whose text contains `offset`.

    A position on a separator itself belongs to the page it ends.
    """
    ranges = page_ranges(content)
    for page, (_start, end) in enumerate(ranges):
        if offset <= end:
            return page
    return len(ranges) - 1


def region_marker_position(
    content: str, page: int, markers_on_page: int, insert_index: int
) -> int:
    """Where to insert a new `REGION_MARKER_LINE` in `content`.

    A page's region markers are kept as a contiguous run of
    `REGION_MARKER_LINE`s at the end of that page's text, ordered the way the
    regions are ordered on the page; `markers_on_page` is how many are there
    already and `insert_index` is the new region's place among them.
    """
    ranges = page_ranges(content)
    page = max(0, min(page, len(ranges) - 1))
    _, end = ranges[page]
    run_start = end - len(REGION_MARKER_LINE) * markers_on_page
    return run_start + len(REGION_MARKER_LINE) * insert_index
