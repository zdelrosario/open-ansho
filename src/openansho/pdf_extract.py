"""Read PDF documents: their text, their page images, and where the two meet.

A PDF is imported the same way as any other document: its text is extracted
into `documents.content`, so every existing coding, navigation and reporting
path works on it unchanged. Three conventions make that flat text addressable
back to the original pages:

- Pages are separated in the content by `PAGE_SEPARATOR` (a form feed on its
  own line — a form feed is the usual convention for a page break in
  extracted text). Page boundaries are therefore derived from the content
  itself rather than stored alongside it, which keeps them correct after the
  text is edited. A page's text starts exactly at the start of its range and
  ends with a newline.
- Each coded rectangular region of a page contributes one `REGION_MARKER`
  character, on its own line at the end of that page's text. A region is
  coded by coding that single character, which is also what makes the vim
  motions treat an image as one character.
- `PdfTextMap` maps between a content offset and the rectangle the character
  at that offset occupies on its page, which is what lets the PDF pane put a
  text cursor, a selection and coded-segment highlights on the page itself.

Unlike `db.py`/`reporting.py`/`text_extract.py` this module does import Qt —
rendering a PDF page means using Qt's PDF engine, there being no other
renderer in the dependency list. It needs no QApplication, though (not even
for `render`), so it stays usable from tests and a future CLI, which is what
the no-Qt rule in the other non-UI modules is really protecting.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QBuffer, QIODevice, QRectF, QSize, QSizeF
from PySide6.QtGui import QImage
from PySide6.QtPdf import QPdfDocument

from openansho.text_extract import DocumentReadError

# A form feed on its own line. Both characters belong to the separator, so a
# page's text is exactly `content[start:end]` for its range — nothing to trim.
PAGE_SEPARATOR = "\f\n"

# U+25AD WHITE RECTANGLE: one character standing in for one coded region of a
# page, picked to be visible (unlike U+FFFC OBJECT REPLACEMENT CHARACTER,
# which has no glyph in the default UI font) and to look like what it
# represents.
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

    Every page's text ends with a newline, which is what lets a region marker
    be appended to a page as its own line (see `region_marker_position`)
    without gluing itself onto the last line of text on the page.
    """
    source = PdfPageSource(data, name)
    return PAGE_SEPARATOR.join(
        source.page_text(page) + "\n" for page in range(source.page_count)
    )


def normalize_page_text(raw: str) -> tuple[str, list[int]]:
    """Normalize one page's extracted text, and say where each character came from.

    Returns the normalized text and, for each of its characters, the index of
    that character in `raw` — the mapping `PdfTextMap` needs to ask the PDF
    where a character sits on the page, since normalizing `\\r\\n` to `\\n`
    shifts every index after it.
    """
    characters: list[str] = []
    indices: list[int] = []
    index = 0
    while index < len(raw):
        character = raw[index]
        if character == "\r":
            characters.append("\n")
            indices.append(index)
            index += 2 if raw[index + 1 : index + 2] == "\n" else 1
        else:
            characters.append(character)
            indices.append(index)
            index += 1

    end = len(characters)
    while end > 0 and characters[end - 1].isspace():
        end -= 1  # the trailing blank space of a page is not worth coding
    return "".join(characters[:end]), indices[:end]


class PdfPageSource:
    """A loaded PDF: page text, page sizes, page images, glyph rectangles.

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
        self._normalized: dict[int, tuple[str, list[int]]] = {}
        self._char_rects: dict[int, list[QRectF]] = {}

    @property
    def page_count(self) -> int:
        return self._document.pageCount()

    def raw_page_text(self, page: int) -> str:
        return self._document.getAllText(page).text()

    def page_text(self, page: int) -> str:
        """One page's text, newline-normalized and without trailing blank space."""
        return self._normalize(page)[0]

    def page_char_indices(self, page: int) -> list[int]:
        """Raw index of each character of `page_text(page)`."""
        return self._normalize(page)[1]

    def _normalize(self, page: int) -> tuple[str, list[int]]:
        if page not in self._normalized:
            self._normalized[page] = normalize_page_text(self.raw_page_text(page))
        return self._normalized[page]

    def page_size(self, page: int) -> QSizeF:
        return self._document.pagePointSize(page)

    def render(self, page: int, size: QSize) -> QImage:
        return self._document.render(page, size)

    def char_rects(self, page: int) -> list[QRectF]:
        """Rectangle of each raw character of `page`, in page points.

        The per-glyph boxes Qt reports are tight — a lowercase letter's box is
        shorter than a capital's, and a space has none worth drawing — so each
        character is stretched to the full vertical extent of the line it is
        on. A cursor or a highlight drawn from these is then a steady height
        along a line instead of bobbing with the letters.
        """
        if page in self._char_rects:
            return self._char_rects[page]

        text = self.raw_page_text(page)
        rects = [
            self._document.getSelectionAtIndex(page, index, 1).boundingRectangle()
            for index in range(len(text))
        ]
        self._char_rects[page] = _level_rects_by_line(rects)
        return self._char_rects[page]


def _level_rects_by_line(rects: list[QRectF]) -> list[QRectF]:
    """Give every character on a line the same top and height.

    Characters are grouped into lines by where they sit: a character joins
    the line being built if it overlaps that line's vertical extent by more
    than half its own height, and otherwise starts a new one. Empty
    rectangles (spaces, line breaks) inherit the line they fall in, and are
    given the width of a space so the cursor has something to sit on.

    Deciding this by position rather than by reading order matters: a real
    document's extraction order is not simply top-to-bottom. A journal page
    whose margin line numbers come out after its footer jumps back *up* the
    page, and a rule phrased as "a new line starts when the text moves left
    or down" merges the two — making every character in the merged run as
    tall as the gap between them, so clicking one covers half the page.
    """
    leveled: list[QRectF] = list(rects)
    line_start = 0

    def finish(start: int, end: int) -> None:
        line = [rect for rect in rects[start:end] if not rect.isEmpty()]
        if not line:
            return
        top = min(rect.top() for rect in line)
        bottom = max(rect.bottom() for rect in line)
        right_edge = max(rect.right() for rect in line)
        space = max((bottom - top) * 0.4, 1.0)
        previous_right = min(rect.left() for rect in line)
        for index in range(start, end):
            rect = rects[index]
            if rect.isEmpty():
                # A space or a line break: park it just past the last glyph,
                # so the cursor lands somewhere sensible when it sits there.
                left = min(previous_right, right_edge)
                leveled[index] = QRectF(left, top, space, bottom - top)
            else:
                leveled[index] = QRectF(rect.left(), top, rect.width(), bottom - top)
                previous_right = rect.right()

    extent: tuple[float, float] | None = None  # the line so far, as (top, bottom)
    for index, rect in enumerate(rects):
        if rect.isEmpty():
            continue  # a space or a line break carries no position of its own
        if extent is not None and not _shares_line(extent, rect):
            finish(line_start, index)
            line_start = index
            extent = None
        if extent is None:
            extent = (rect.top(), rect.bottom())
        else:
            # Measuring against the line so far, rather than against the
            # previous character, keeps a run of slightly-drifting
            # characters from walking the line's extent down the page.
            extent = (min(extent[0], rect.top()), max(extent[1], rect.bottom()))
    finish(line_start, len(rects))
    return leveled


def _shares_line(extent: tuple[float, float], rect: QRectF) -> bool:
    """Whether `rect` sits on the line currently spanning `extent`."""
    top, bottom = extent
    overlap = min(bottom, rect.bottom()) - max(top, rect.top())
    shorter = min(bottom - top, rect.height())
    return overlap > 0.5 * shorter if shorter > 0 else overlap > 0


def page_ranges(content: str) -> list[tuple[int, int]]:
    """Character range of each page's text in `content`, one pair per page.

    Ranges exclude the `PAGE_SEPARATOR` between them, so page `n`'s text is
    exactly `content[start:end]`.
    """
    ranges = []
    start = 0
    while True:
        separator = content.find(PAGE_SEPARATOR[0], start)
        if separator == -1:
            ranges.append((start, len(content)))
            return ranges
        ranges.append((start, separator))
        # Tolerate a separator whose newline an edit removed.
        following = content[separator + 1 : separator + 2]
        start = separator + (len(PAGE_SEPARATOR) if following == "\n" else 1)


def page_for_offset(content: str, offset: int) -> int:
    """Index of the page whose text contains `offset`.

    A position on a separator itself belongs to the page it ends.
    """
    return _page_for_offset(page_ranges(content), offset)


def _page_for_offset(ranges: list[tuple[int, int]], offset: int) -> int:
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


class PdfTextMap:
    """Maps between offsets in a document's content and places on its pages.

    Built fresh whenever the content changes, and cheap to build: the per-page
    glyph rectangles behind it are computed once, lazily, by `PdfPageSource`.
    """

    def __init__(self, content: str, source: PdfPageSource) -> None:
        self._content = content
        self._source = source
        self._ranges = page_ranges(content)

    @property
    def page_count(self) -> int:
        return len(self._ranges)

    def page_range(self, page: int) -> tuple[int, int]:
        return self._ranges[page]

    def page_for_offset(self, offset: int) -> int:
        return _page_for_offset(self._ranges, offset)

    def rect_for_offset(self, offset: int) -> tuple[int, QRectF] | None:
        """The page and rectangle of the character at `offset`, if it has one.

        Region markers and the page separators have no glyph on the page, and
        return None — callers decide what to draw for them.
        """
        page = self.page_for_offset(offset)
        if page >= self._source.page_count:
            return None
        start, end = self._ranges[page]
        index = offset - start
        if index < 0 or offset >= end:
            return None
        indices = self._source.page_char_indices(page)
        if index >= len(indices):
            return None
        rects = self._source.char_rects(page)
        raw_index = indices[index]
        if raw_index >= len(rects):
            return None
        rect = rects[raw_index]
        return (page, rect) if not rect.isEmpty() else None

    def rects_for_range(self, start: int, end: int) -> list[tuple[int, QRectF]]:
        """One rectangle per run of characters in [start, end) sharing a line.

        Adjacent characters on the same line are merged, so a coded span is
        painted as a few wide rectangles rather than one per letter.
        """
        runs: list[tuple[int, QRectF]] = []
        for offset in range(start, end):
            located = self.rect_for_offset(offset)
            if located is None:
                continue
            page, rect = located
            if runs:
                last_page, last_rect = runs[-1]
                if last_page == page and _same_line(last_rect, rect):
                    runs[-1] = (page, last_rect.united(rect))
                    continue
            runs.append((page, QRectF(rect)))
        return runs

    def offset_at(self, page: int, point) -> int:
        """The content offset of the character nearest `point` on `page`.

        Used to put the text cursor where the user clicked. Picks the closest
        character on the nearest line, so a click past the end of a line lands
        on that line's end rather than somewhere else entirely.
        """
        if page >= len(self._ranges):
            return len(self._content)
        start, end = self._ranges[page]
        indices = self._source.page_char_indices(page)
        rects = self._source.char_rects(page)
        if not indices:
            return start

        best_offset = start
        best_score = None
        for index, raw_index in enumerate(indices):
            if raw_index >= len(rects):
                continue
            rect = rects[raw_index]
            if rect.isEmpty():
                continue
            # Lines first, then horizontal distance within the line, so a
            # click to the right of a line stays on that line.
            if rect.top() <= point.y() <= rect.bottom():
                vertical = 0.0
            else:
                vertical = min(abs(point.y() - rect.top()), abs(point.y() - rect.bottom()))
            horizontal = 0.0
            if point.x() < rect.left():
                horizontal = rect.left() - point.x()
            elif point.x() > rect.right():
                horizontal = point.x() - rect.right()
            score = (vertical * 1000.0) + horizontal
            if best_score is None or score < best_score:
                best_score = score
                best_offset = min(start + index, end)
        return best_offset

    def is_over_text(self, page: int, point) -> bool:
        """Whether `point` lands on a character of `page`.

        What decides between starting a text selection and drawing a region.
        """
        if page >= self._source.page_count:
            return False
        for rect in self._source.char_rects(page):
            if not rect.isEmpty() and rect.contains(point):
                return True
        return False


def _same_line(first: QRectF, second: QRectF) -> bool:
    return abs(first.top() - second.top()) < 0.5 and abs(first.height() - second.height()) < 0.5
