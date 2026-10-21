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

import heapq
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

# How far around its glyphs a line of text reaches for a press, in multiples
# of the height of its runs (see `PdfPageSource.text_zones`): runs of one
# line closer than JOIN are one stretch of text, and each stretch is padded
# by the two PADDINGs. A run's box hugs the glyphs — about three quarters of
# the font size — so a full height above and below is what it takes to
# close the leading of double-spaced text.
TEXT_ZONE_JOIN = 2.0
TEXT_ZONE_PADDING_X = 0.5
TEXT_ZONE_PADDING_Y = 1.0


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
        self._text_zones: dict[int, list[QRectF]] = {}
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
        """Whether `point` lands within the text of `page`.

        Measured against `text_zones` rather than the bare runs, so a press
        in the gap between two lines or two words still counts as on the
        text — only a press clear of it starts a region.
        """
        return any(zone.contains(point) for zone in self.text_zones(page))

    def text_zones(self, page: int) -> list[QRectF]:
        """The areas of `page` a press counts as being on the text.

        A run's rectangle hugs its glyphs, leaving thin gaps between lines
        and between the runs of one line that read as text to the eye. Each
        line's runs are joined across gaps narrower than `TEXT_ZONE_JOIN`
        line heights, then padded by `TEXT_ZONE_PADDING_X`/`_Y` — enough to
        close the leading of single- and double-spaced text without
        reaching across a column gutter.
        """
        if page in self._text_zones:
            return self._text_zones[page]

        zones = []
        for line in self.page_lines(page):
            for zone in _join_runs(line.boxes):
                pad_x = zone.height() * TEXT_ZONE_PADDING_X
                pad_y = zone.height() * TEXT_ZONE_PADDING_Y
                zones.append(zone.adjusted(-pad_x, -pad_y, pad_x, pad_y))
        self._text_zones[page] = zones
        return zones

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


def _join_runs(boxes: tuple[QRectF, ...]) -> list[QRectF]:
    """A line's runs, with neighbors closer than `TEXT_ZONE_JOIN` united."""
    joined: list[QRectF] = []
    for box in sorted(boxes, key=QRectF.left):
        if joined:
            last = joined[-1]
            reach = max(last.height(), box.height()) * TEXT_ZONE_JOIN
            if box.left() - last.right() < reach:
                joined[-1] = last.united(box)
                continue
        joined.append(QRectF(box))
    return joined


def _reading_order(boxes: list[QRectF]) -> list[int]:
    """The order to read lines placed at `boxes` in, as indices into it.

    The content's own order, except where it contradicts the page: a line
    is never read before a line above it that it shares any width with,
    nor before a line to its left on the same row. Of the lines that are
    free to come next, the earliest in the content goes first — so the two
    columns of an article, which the content gives one after the other,
    stay that way instead of being interleaved row by row, while a title
    the file happened to write last moves back to the top.
    """
    count = len(boxes)
    following: list[list[int]] = [[] for _ in range(count)]
    waiting_on = [0] * count
    for earlier in range(count):
        for later in range(count):
            if earlier != later and _reads_before(boxes[earlier], boxes[later]):
                following[earlier].append(later)
                waiting_on[later] += 1

    ready = [index for index in range(count) if waiting_on[index] == 0]
    heapq.heapify(ready)
    order: list[int] = []
    done = [False] * count
    while len(order) < count:
        if ready:
            index = heapq.heappop(ready)
        else:
            # Skewed boxes can in principle constrain each other in a
            # circle; fall back to the content's order to break it.
            index = next(i for i in range(count) if not done[i])
        if done[index]:
            continue
        done[index] = True
        order.append(index)
        for later in following[index]:
            waiting_on[later] -= 1
            if waiting_on[later] == 0 and not done[later]:
                heapq.heappush(ready, later)
    return order


def _reads_before(earlier: QRectF, later: QRectF) -> bool:
    """Whether the line at `earlier` has to be read before the one at `later`."""
    slack = min(earlier.height(), later.height()) * 0.25
    share_width = earlier.left() < later.right() and later.left() < earlier.right()
    if share_width and earlier.bottom() <= later.top() + slack:
        return True  # above it
    same_row = (
        earlier.top() < later.bottom() - slack and later.top() < earlier.bottom() - slack
    )
    return same_row and earlier.right() <= later.left()


def _united(rects) -> QRectF:
    united = QRectF(rects[0])
    for rect in rects[1:]:
        united = united.united(rect)
    return united


def _close_line_gaps(bands: list[QRectF]) -> None:
    """Stretch consecutive lines' bands, in place, to meet halfway across the gap.

    Only a gap narrow enough to be the leading within a paragraph — the
    same reach `PdfPageSource.text_zones` gives a line — so the space
    between paragraphs, or between a page's lines and a stray caption,
    stays unselected-looking.
    """
    for upper, lower in zip(bands, bands[1:]):
        gap = lower.top() - upper.bottom()
        reach = min(upper.height(), lower.height()) * TEXT_ZONE_PADDING_Y * 2
        if 0 < gap <= reach:
            middle = upper.bottom() + gap / 2
            upper.setBottom(middle)
            lower.setTop(middle)


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
        self._selection_cache: dict[tuple[int, int], list[tuple[int, QRectF]]] = {}
        self._display_lines: dict[int, list[tuple[int, int]]] = {}

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

    def selection_rects(self, start: int, end: int) -> list[tuple[int, QRectF]]:
        """One solid rectangle per line of text in [start, end).

        How a selection is drawn, to look the way it does in the text pane:
        a band the height of the line, spanning from the first selected
        character on it to the last, with consecutive lines of a paragraph
        meeting rather than leaving a stripe of page between them. The runs
        `rects_for_range` returns can't be painted as they are — a PDF that
        places its words, or its letters, one at a time comes back as a box
        per word or letter, each hugging its own glyphs.
        """
        cached = self._selection_cache.get((start, end))
        if cached is not None:
            return cached
        by_page: dict[int, list[QRectF]] = {}
        for page, rect in self.rects_for_range(start, end):
            by_page.setdefault(page, []).append(rect)

        rects: list[tuple[int, QRectF]] = []
        for page, runs in by_page.items():
            bands = []
            for line in self._source.page_lines(page):
                extent = _united(line.boxes)
                on_line = [
                    run
                    for run in runs
                    if extent.top() <= run.center().y() <= extent.bottom()
                    and run.right() >= extent.left()
                    and run.left() <= extent.right()
                ]
                if not on_line:
                    continue
                runs = [run for run in runs if run not in on_line]
                covered = _united(on_line)
                bands.append(
                    QRectF(covered.left(), extent.top(), covered.width(), extent.height())
                )
            bands.extend(runs)  # anything no line claimed, drawn as it came
            _close_line_gaps(bands)
            rects.extend((page, band) for band in bands)
        self._selection_cache[(start, end)] = rects
        return rects

    def display_lines(self, page: int) -> list[tuple[int, int]]:
        """The [start, end) of each content line of `page`, in reading order.

        A PDF's text comes out in whatever order the file wrote it, which
        need not be the order it reads in — the tutorial's title is written
        last, so walking the content line by line visits it after the body.
        The line motions walk this instead (see `_reading_order`). A line
        with no glyphs on the page — a region marker, a blank line — keeps
        its place after the line it follows in the content, or the end of
        the page for the run of markers that ends it. Built a page at a
        time, when first asked, since placing a page's lines means asking
        the PDF about each of them.
        """
        if page in self._display_lines:
            return self._display_lines[page]

        start, end = self._ranges[page]
        lines = []
        position = start
        for text in self._content[start:end].split("\n"):
            lines.append((position, position + len(text)))
            position += len(text) + 1
        if len(lines) > 1 and lines[-1][0] == end:
            lines.pop()  # what follows the page's final newline is not a line

        placed: list[tuple[QRectF, list[tuple[int, int]]]] = []
        leading: list[tuple[int, int]] = []
        for line in lines:
            box = self._line_box(page, line[0]) if line[1] > line[0] else None
            if box is not None:
                placed.append((box, [line]))
            elif placed:
                placed[-1][1].append(line)
            else:
                leading.append(line)
        trailing = []
        if placed:
            # The lines after the last placed one end the page wherever that
            # line is read, rather than following it to the top of the page.
            last_box, last_lines = placed[-1]
            placed[-1] = (last_box, last_lines[:1])
            trailing = last_lines[1:]

        ordered = list(leading)
        for index in _reading_order([box for box, _lines in placed]):
            ordered.extend(placed[index][1])
        ordered.extend(trailing)
        self._display_lines[page] = ordered
        return ordered

    def adjacent_line(self, offset: int, step: int) -> tuple[int, int] | None:
        """The line read `step` (1 or -1) lines on from the one holding `offset`.

        Crosses onto the next or previous page past the end of this one, and
        is None past the end of the document.
        """
        page = self.page_for_offset(offset)
        lines = self.display_lines(page)
        index = next(
            (i for i, (start, end) in enumerate(lines) if start <= offset <= end), None
        )
        if index is not None and 0 <= index + step < len(lines):
            return lines[index + step]
        if index is None and lines:
            # On a page separator: before the first line of the page that
            # starts there, or past the end of the one before it.
            if offset < lines[0][0]:
                if step > 0:
                    return lines[0]
            elif step < 0:
                return lines[-1]
        page += step
        while 0 <= page < len(self._ranges):
            lines = self.display_lines(page)
            if lines:
                return lines[0] if step > 0 else lines[-1]
            page += step
        return None

    def first_display_line(self) -> tuple[int, int] | None:
        for page in range(len(self._ranges)):
            lines = self.display_lines(page)
            if lines:
                return lines[0]
        return None

    def last_display_line(self) -> tuple[int, int] | None:
        for page in reversed(range(len(self._ranges))):
            lines = self.display_lines(page)
            if lines:
                return lines[-1]
        return None

    def _line_box(self, page: int, offset: int) -> QRectF | None:
        """Where the line of text starting at content `offset` sits on `page`."""
        raw_index = self._raw_index(page, offset)
        if raw_index is None:
            return None
        line = self._source.line_at(page, raw_index)
        return _united(line.boxes) if line is not None else None

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
        """Whether `point` lands on the text of `page`, gaps between lines included.

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


