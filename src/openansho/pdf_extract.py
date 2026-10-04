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

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QBuffer, QIODevice, QPointF, QRectF, QSize, QSizeF
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
    """A loaded PDF: its text, its page images, and where the two line up.

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
        self._page_lines: dict[int, list[TextLine]] = {}
        self._char_rects: dict[tuple[int, int], QRectF | None] = {}

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

    # -- geometry ---------------------------------------------------------
    #
    # Every `QPdfDocument.getSelection*` call costs the same (~1.3ms on a
    # dense page) however much text it asks about, because the engine walks
    # the page's text each time. So geometry is gathered a *line* or a
    # *range* at a time and cached, never a character at a time: asking per
    # character made the first click on a page of a journal article take
    # four and a half seconds.

    def page_lines(self, page: int) -> list[TextLine]:
        """Every line of `page`, with the rectangles its runs occupy.

        One call per line of text rather than one per character. A line can
        hold more than one rectangle — a style change, or a superscript,
        starts a new run — and they are kept apart rather than merged, so a
        character is leveled to the run it is actually on.
        """
        if page in self._page_lines:
            return self._page_lines[page]

        raw = self.raw_page_text(page)
        lines = []
        for start, end in _line_spans(raw):
            boxes = self._bounds(page, start, end - start)
            if boxes:
                lines.append(TextLine(start, end, tuple(boxes)))
        self._page_lines[page] = lines
        return lines

    def line_at(self, page: int, raw_index: int) -> TextLine | None:
        for line in self.page_lines(page):
            if line.start <= raw_index < line.end:
                return line
        return None

    def char_rect(self, page: int, raw_index: int) -> QRectF | None:
        """The rectangle of one character, or None where it has no glyph.

        Leveled to the full height of the run it sits on, so a cursor drawn
        from it is a steady band along the line instead of bobbing with the
        letters. Spaces and line breaks have no glyph and no rectangle.
        """
        key = (page, raw_index)
        if key not in self._char_rects:
            boxes = self._bounds(page, raw_index, 1)
            rect = boxes[0] if boxes else None
            if rect is not None:
                line = self.line_at(page, raw_index)
                run = line.run_for(rect) if line is not None else None
                if run is not None:
                    rect = QRectF(rect.left(), run.top(), rect.width(), run.height())
            self._char_rects[key] = rect
        return self._char_rects[key]

    def range_rects(self, page: int, raw_start: int, raw_end: int) -> list[QRectF]:
        """The rectangles covering raw characters [start, end) of `page`.

        One per run of the selection, which is what the engine returns — so
        a coded span costs one call however long it is.
        """
        if raw_end <= raw_start:
            return []
        return self._bounds(page, raw_start, raw_end - raw_start)

    def index_at(self, page: int, point: QPointF) -> int | None:
        """Raw index of the character at `point`, or None if it is off the text."""
        located = self._run_at(page, point)
        if located is None:
            return None
        line, run = located
        # Within a run, characters read left to right, so the right edge of
        # the first k of them only grows with k — binary search it rather
        # than asking about each character in turn.
        low, high = 0, line.end - line.start
        while low < high:
            middle = (low + high) // 2
            if self._prefix_right(page, line, run, middle + 1) < point.x():
                low = middle + 1
            else:
                high = middle
        return min(line.start + low, line.end - 1)

    def is_over_text(self, page: int, point: QPointF) -> bool:
        """Whether `point` lands on a line of text on `page`."""
        return self._run_at(page, point) is not None

    def _run_at(self, page: int, point: QPointF) -> tuple[TextLine, QRectF] | None:
        for line in self.page_lines(page):
            for run in line.boxes:
                if run.contains(point):
                    return line, run
        return None

    def _prefix_right(self, page: int, line: TextLine, run: QRectF, count: int) -> float:
        """Right edge of `line`'s first `count` characters, within `run`'s band."""
        boxes = [
            box
            for box in self._bounds(page, line.start, count)
            if box.bottom() > run.top() and box.top() < run.bottom()
        ]
        return max((box.right() for box in boxes), default=run.left())

    def _bounds(self, page: int, start: int, count: int) -> list[QRectF]:
        selection = self._document.getSelectionAtIndex(page, start, count)
        return [
            polygon.boundingRect()
            for polygon in selection.bounds()
            if not polygon.boundingRect().isEmpty()
        ]


@dataclass(frozen=True)
class TextLine:
    """One line of a page's text: where it starts and ends, and where it sits.

    `start`/`end` are indices into the page's *raw* text. `boxes` holds one
    rectangle per run on the line, kept separate rather than united so that
    a character is leveled to its own run.
    """

    start: int
    end: int
    boxes: tuple[QRectF, ...]

    def run_for(self, rect: QRectF) -> QRectF | None:
        """The run `rect` sits on: the one it overlaps vertically the most."""
        best, best_overlap = None, 0.0
        for box in self.boxes:
            overlap = min(box.bottom(), rect.bottom()) - max(box.top(), rect.top())
            if overlap > best_overlap:
                best, best_overlap = box, overlap
        return best


def _line_spans(raw: str) -> list[tuple[int, int]]:
    """The [start, end) of each line of `raw`, excluding the line breaks."""
    spans = []
    start = 0
    for index, character in enumerate(raw):
        if character in "\r\n":
            if index > start:
                spans.append((start, index))
            start = index + 1
    if len(raw) > start:
        spans.append((start, len(raw)))
    return spans


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
        # Ranges are asked about again on every repaint — once per coded
        # span, per frame — and the answers are in page coordinates, so they
        # hold good across scrolling and zooming. A new map is built whenever
        # the content changes, which is what empties this.
        self._range_cache: dict[tuple[int, int], list[tuple[int, QRectF]]] = {}

    @property
    def page_count(self) -> int:
        return len(self._ranges)

    def page_range(self, page: int) -> tuple[int, int]:
        return self._ranges[page]

    def page_for_offset(self, offset: int) -> int:
        return _page_for_offset(self._ranges, offset)

    def rect_for_offset(self, offset: int) -> tuple[int, QRectF] | None:
        """The page and rectangle of the character at `offset`, if it has one.

        Spaces, region markers and the page separators have no glyph on the
        page and return None — callers decide what to draw for them.
        """
        page = self.page_for_offset(offset)
        raw_index = self._raw_index(page, offset)
        if raw_index is None:
            return None
        rect = self._source.char_rect(page, raw_index)
        return (page, rect) if rect is not None else None

    def rects_for_range(self, start: int, end: int) -> list[tuple[int, QRectF]]:
        """One rectangle per run of characters in [start, end).

        Asked of the PDF a page at a time rather than a character at a time:
        a coded span of any length costs one call per page it touches.
        """
        cached = self._range_cache.get((start, end))
        if cached is not None:
            return cached
        rects: list[tuple[int, QRectF]] = []
        for page in range(self.page_for_offset(start), self.page_for_offset(end - 1) + 1):
            page_start, page_end = self._ranges[page]
            first = self._raw_index(page, max(start, page_start))
            last = self._last_raw_index(page, min(end, page_end))
            if first is None or last is None or last <= first:
                continue
            rects.extend(
                (page, rect) for rect in self._source.range_rects(page, first, last)
            )
        self._range_cache[(start, end)] = rects
        return rects

    def offset_at(self, page: int, point: QPointF) -> int:
        """The content offset of the character at `point` on `page`.

        Used to put the text cursor where the user clicked. A click off the
        text lands on the nearest character of the nearest line, so clicking
        past the end of a line stays on that line.
        """
        if page >= len(self._ranges) or page >= self._source.page_count:
            return len(self._content)
        start, _end = self._ranges[page]
        raw_index = self._source.index_at(page, point)
        if raw_index is None:
            raw_index = self._source.index_at(page, self._nearest_text_point(page, point))
        if raw_index is None:
            return start
        return start + self._normalized_index(page, raw_index)

    def is_over_text(self, page: int, point: QPointF) -> bool:
        """Whether `point` lands on a character of `page`.

        What decides between starting a text selection and drawing a region.
        """
        if page >= self._source.page_count:
            return False
        return self._source.is_over_text(page, point)

    def _nearest_text_point(self, page: int, point: QPointF) -> QPointF:
        """`point` pulled onto the closest run of text on the page."""
        best, best_distance = point, None
        for line in self._source.page_lines(page):
            for run in line.boxes:
                x = min(max(point.x(), run.left()), run.right())
                y = min(max(point.y(), run.top()), run.bottom())
                distance = (x - point.x()) ** 2 + (y - point.y()) ** 2
                if best_distance is None or distance < best_distance:
                    best, best_distance = QPointF(x, y), distance
        return best

    def _raw_index(self, page: int, offset: int) -> int | None:
        """The raw index of the character at content `offset`, if it is one."""
        if page >= self._source.page_count:
            return None
        start, end = self._ranges[page]
        index = offset - start
        if index < 0 or offset >= end:
            return None
        indices = self._source.page_char_indices(page)
        return indices[index] if index < len(indices) else None

    def _last_raw_index(self, page: int, offset: int) -> int | None:
        """One past the raw index of the last character before content `offset`."""
        start, _end = self._ranges[page]
        indices = self._source.page_char_indices(page)
        index = min(offset - start, len(indices))
        return indices[index - 1] + 1 if index > 0 else None

    def _normalized_index(self, page: int, raw_index: int) -> int:
        """Where a raw index lands in the page's normalized text."""
        indices = self._source.page_char_indices(page)
        for index, raw in enumerate(indices):
            if raw >= raw_index:
                return index
        return len(indices)


