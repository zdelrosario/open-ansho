"""SQLite-backed data access layer for OpenAnsho projects.

A project is a single .sqlite file containing documents, a codebook
(codes, possibly nested), and the coded segments linking the two.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

DOCUMENT_KIND_TEXT = "text"
DOCUMENT_KIND_PDF = "pdf"

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    kind TEXT,
    source_data BLOB
);

CREATE TABLE IF NOT EXISTS codes (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    parent_id INTEGER REFERENCES codes(id) ON DELETE CASCADE,
    color TEXT,
    color_class TEXT,
    description TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS segments (
    id INTEGER PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    code_id INTEGER NOT NULL REFERENCES codes(id) ON DELETE CASCADE,
    start_offset INTEGER NOT NULL,
    end_offset INTEGER NOT NULL,
    memo TEXT,
    created_by TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS regions (
    id INTEGER PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page INTEGER NOT NULL,
    text_offset INTEGER NOT NULL,
    x REAL NOT NULL,
    y REAL NOT NULL,
    width REAL NOT NULL,
    height REAL NOT NULL,
    points TEXT,
    created_by TEXT,
    created_at TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class Document:
    id: int
    name: str
    content: str
    created_at: str
    # Both default so a row from a project created before PDF support (where
    # `_migrate` adds the columns as NULL) still builds a Document.
    kind: str | None = None
    source_data: bytes | None = None

    @property
    def is_pdf(self) -> bool:
        return self.kind == DOCUMENT_KIND_PDF


@dataclass(frozen=True)
class Region:
    """An area of one PDF page, coded like a span of text.

    `text_offset` points at this region's marker character in the owning
    document's `content` (see `pdf_extract.REGION_MARKER`): coding a region
    is an ordinary `segments` row covering that single character, so
    highlights, multi-code stripes, counts and exports need no special case.

    `points` is the region's outline — `[[x, y], ...]` as JSON — and `x`/`y`/
    `width`/`height` its bounding box. Both are fractions of the page's width
    and height, so they survive being rendered at any zoom. A rectangle is
    stored as its four corners, so the rectangle and freehand tools produce
    the same kind of shape and only differ in how the user draws it; use
    `outline()` rather than reading `points` directly, since it falls back to
    the bounding box for a region stored before freehand existed.
    """

    id: int
    document_id: int
    page: int
    text_offset: int
    x: float
    y: float
    width: float
    height: float
    points: str | None
    created_by: str | None
    created_at: str

    def outline(self) -> list[tuple[float, float]]:
        """The region's outline in page fractions, corners included."""
        if self.points:
            return [(float(x), float(y)) for x, y in json.loads(self.points)]
        return [
            (self.x, self.y),
            (self.x + self.width, self.y),
            (self.x + self.width, self.y + self.height),
            (self.x, self.y + self.height),
        ]


@dataclass(frozen=True)
class Code:
    id: int
    name: str
    parent_id: int | None
    color: str | None
    color_class: str | None
    description: str | None
    created_at: str


@dataclass(frozen=True)
class Segment:
    id: int
    document_id: int
    code_id: int
    start_offset: int
    end_offset: int
    memo: str | None
    created_by: str | None
    created_at: str


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    init_db(conn)
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    _migrate(conn)
    conn.commit()


def _migrate(conn: sqlite3.Connection) -> None:
    """Add columns introduced after a project's initial creation."""
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(segments)")}
    if "created_by" not in columns:
        conn.execute("ALTER TABLE segments ADD COLUMN created_by TEXT")

    code_columns = {row["name"] for row in conn.execute("PRAGMA table_info(codes)")}
    if "color_class" not in code_columns:
        conn.execute("ALTER TABLE codes ADD COLUMN color_class TEXT")
    if "description" not in code_columns:
        conn.execute("ALTER TABLE codes ADD COLUMN description TEXT")

    region_columns = {row["name"] for row in conn.execute("PRAGMA table_info(regions)")}
    if region_columns and "points" not in region_columns:
        conn.execute("ALTER TABLE regions ADD COLUMN points TEXT")

    document_columns = {row["name"] for row in conn.execute("PRAGMA table_info(documents)")}
    if "kind" not in document_columns:
        conn.execute("ALTER TABLE documents ADD COLUMN kind TEXT")
    if "source_data" not in document_columns:
        conn.execute("ALTER TABLE documents ADD COLUMN source_data BLOB")


def create_document(
    conn: sqlite3.Connection,
    name: str,
    content: str,
    kind: str = DOCUMENT_KIND_TEXT,
    source_data: bytes | None = None,
) -> Document:
    """Insert a document.

    `source_data` holds the bytes of the file the content was extracted from,
    and is only stored for kinds that need the original to render (PDFs), so
    a project file stays self-contained rather than depending on the imported
    file staying where it was.
    """
    cur = conn.execute(
        "INSERT INTO documents (name, content, created_at, kind, source_data) "
        "VALUES (?, ?, ?, ?, ?)",
        (name, content, _now(), kind, source_data),
    )
    conn.commit()
    return get_document(conn, cur.lastrowid)


def get_document(conn: sqlite3.Connection, document_id: int) -> Document | None:
    row = conn.execute(
        "SELECT * FROM documents WHERE id = ?", (document_id,)
    ).fetchone()
    return Document(**row) if row else None


def list_documents(conn: sqlite3.Connection) -> list[Document]:
    rows = conn.execute("SELECT * FROM documents ORDER BY id").fetchall()
    return [Document(**row) for row in rows]


def get_document_by_name(conn: sqlite3.Connection, name: str) -> Document | None:
    row = conn.execute(
        "SELECT * FROM documents WHERE name = ?", (name,)
    ).fetchone()
    return Document(**row) if row else None


def delete_document(conn: sqlite3.Connection, document_id: int) -> None:
    conn.execute("DELETE FROM documents WHERE id = ?", (document_id,))
    conn.commit()


def update_document_content(
    conn: sqlite3.Connection, document_id: int, content: str
) -> Document:
    conn.execute(
        "UPDATE documents SET content = ? WHERE id = ?", (content, document_id)
    )
    conn.commit()
    return get_document(conn, document_id)


def create_code(
    conn: sqlite3.Connection,
    name: str,
    parent_id: int | None = None,
    color: str | None = None,
    color_class: str | None = None,
    description: str | None = None,
) -> Code:
    cur = conn.execute(
        "INSERT INTO codes (name, parent_id, color, color_class, description, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (name, parent_id, color, color_class, description, _now()),
    )
    conn.commit()
    return get_code(conn, cur.lastrowid)


def get_code(conn: sqlite3.Connection, code_id: int) -> Code | None:
    row = conn.execute("SELECT * FROM codes WHERE id = ?", (code_id,)).fetchone()
    return Code(**row) if row else None


def list_codes(conn: sqlite3.Connection) -> list[Code]:
    rows = conn.execute("SELECT * FROM codes ORDER BY id").fetchall()
    return [Code(**row) for row in rows]


def rename_code(conn: sqlite3.Connection, code_id: int, name: str) -> Code:
    conn.execute("UPDATE codes SET name = ? WHERE id = ?", (name, code_id))
    conn.commit()
    return get_code(conn, code_id)


def set_code_description(conn: sqlite3.Connection, code_id: int, description: str | None) -> Code:
    conn.execute("UPDATE codes SET description = ? WHERE id = ?", (description, code_id))
    conn.commit()
    return get_code(conn, code_id)


def set_code_parent(conn: sqlite3.Connection, code_id: int, parent_id: int | None) -> Code:
    conn.execute("UPDATE codes SET parent_id = ? WHERE id = ?", (parent_id, code_id))
    conn.commit()
    return get_code(conn, code_id)


def set_code_color(
    conn: sqlite3.Connection, code_id: int, color: str, color_class: str
) -> Code:
    conn.execute(
        "UPDATE codes SET color = ?, color_class = ? WHERE id = ?",
        (color, color_class, code_id),
    )
    conn.commit()
    return get_code(conn, code_id)


def count_codes_by_color_class(conn: sqlite3.Connection) -> dict[str, int]:
    """Map color_class -> number of codes (root or child) assigned to it."""
    rows = conn.execute(
        "SELECT color_class, COUNT(*) AS count FROM codes "
        "WHERE color_class IS NOT NULL GROUP BY color_class"
    ).fetchall()
    return {row["color_class"]: row["count"] for row in rows}


def delete_code(conn: sqlite3.Connection, code_id: int) -> None:
    """Delete a code, re-parenting its children to its own parent (or to root).

    `codes.parent_id` cascades on delete, so children would otherwise be
    deleted along with their parent; re-pointing them first avoids that.
    """
    code = get_code(conn, code_id)
    if code is None:
        return
    conn.execute(
        "UPDATE codes SET parent_id = ? WHERE parent_id = ?", (code.parent_id, code_id)
    )
    conn.execute("DELETE FROM codes WHERE id = ?", (code_id,))
    conn.commit()


def merge_codes(conn: sqlite3.Connection, keep_id: int, merge_id: int) -> None:
    """Merge `merge_id` into `keep_id`.

    Segments coded with `merge_id` are re-coded to `keep_id`, dropping any
    that would exactly duplicate a segment `keep_id` already has. Children of
    `merge_id` are re-parented to `keep_id` before it's deleted, the same
    cascade-dodging move `delete_code` makes for its own children.
    """
    keep_segments = {
        (s.document_id, s.start_offset, s.end_offset, s.created_by)
        for s in list_segments_for_code(conn, keep_id)
    }
    for segment in list_segments_for_code(conn, merge_id):
        key = (segment.document_id, segment.start_offset, segment.end_offset, segment.created_by)
        if key in keep_segments:
            conn.execute("DELETE FROM segments WHERE id = ?", (segment.id,))
        else:
            conn.execute(
                "UPDATE segments SET code_id = ? WHERE id = ?", (keep_id, segment.id)
            )
            keep_segments.add(key)
    conn.execute(
        "UPDATE codes SET parent_id = ? WHERE parent_id = ?", (keep_id, merge_id)
    )
    conn.execute("DELETE FROM codes WHERE id = ?", (merge_id,))
    conn.commit()


def create_segment(
    conn: sqlite3.Connection,
    document_id: int,
    code_id: int,
    start_offset: int,
    end_offset: int,
    memo: str | None = None,
    created_by: str | None = None,
) -> Segment:
    if end_offset <= start_offset:
        raise ValueError("end_offset must be greater than start_offset")
    existing = conn.execute(
        """
        SELECT * FROM segments
        WHERE document_id = ? AND code_id = ? AND start_offset = ? AND end_offset = ?
            AND created_by IS ?
        """,
        (document_id, code_id, start_offset, end_offset, created_by),
    ).fetchone()
    if existing is not None:
        return Segment(**existing)
    cur = conn.execute(
        """
        INSERT INTO segments
            (document_id, code_id, start_offset, end_offset, memo, created_by, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (document_id, code_id, start_offset, end_offset, memo, created_by, _now()),
    )
    conn.commit()
    return get_segment(conn, cur.lastrowid)


def get_segment(conn: sqlite3.Connection, segment_id: int) -> Segment | None:
    row = conn.execute(
        "SELECT * FROM segments WHERE id = ?", (segment_id,)
    ).fetchone()
    return Segment(**row) if row else None


def list_segments_for_document(
    conn: sqlite3.Connection, document_id: int
) -> list[Segment]:
    rows = conn.execute(
        "SELECT * FROM segments WHERE document_id = ? ORDER BY start_offset",
        (document_id,),
    ).fetchall()
    return [Segment(**row) for row in rows]


def list_segments_for_code(conn: sqlite3.Connection, code_id: int) -> list[Segment]:
    rows = conn.execute(
        "SELECT * FROM segments WHERE code_id = ? ORDER BY id", (code_id,)
    ).fetchall()
    return [Segment(**row) for row in rows]


def list_all_segments(conn: sqlite3.Connection) -> list[Segment]:
    rows = conn.execute("SELECT * FROM segments ORDER BY id").fetchall()
    return [Segment(**row) for row in rows]


def list_distinct_usernames(conn: sqlite3.Connection) -> list[str | None]:
    """Distinct `segments.created_by` values with at least one segment.

    `None` is included if any segment has no recorded creator.
    """
    rows = conn.execute("SELECT DISTINCT created_by FROM segments").fetchall()
    return [row["created_by"] for row in rows]


def count_segments_by_code(
    conn: sqlite3.Connection, document_id: int | None = None
) -> dict[int, int]:
    """Map code_id -> number of segments coded with it.

    Codes with no segments are omitted, so callers should default to 0.
    """
    if document_id is None:
        rows = conn.execute(
            "SELECT code_id, COUNT(*) AS count FROM segments GROUP BY code_id"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT code_id, COUNT(*) AS count FROM segments WHERE document_id = ? "
            "GROUP BY code_id",
            (document_id,),
        ).fetchall()
    return {row["code_id"]: row["count"] for row in rows}


def delete_segment(conn: sqlite3.Connection, segment_id: int) -> None:
    conn.execute("DELETE FROM segments WHERE id = ?", (segment_id,))
    conn.commit()


def update_segment_offsets(
    conn: sqlite3.Connection, segment_id: int, start_offset: int, end_offset: int
) -> Segment:
    conn.execute(
        "UPDATE segments SET start_offset = ?, end_offset = ? WHERE id = ?",
        (start_offset, end_offset, segment_id),
    )
    conn.commit()
    return get_segment(conn, segment_id)


def split_segment(
    conn: sqlite3.Connection, segment_id: int, first_end: int, second_start: int
) -> tuple[Segment, Segment]:
    """Cut a segment in two: itself up to `first_end`, a copy from `second_start`.

    The copy keeps the original's code, memo, author and timestamp, so the two
    pieces read as the one coding they were rather than as a new one.
    """
    segment = get_segment(conn, segment_id)
    if not segment.start_offset < first_end <= second_start < segment.end_offset:
        raise ValueError("split points must fall inside the segment, in order")
    conn.execute("UPDATE segments SET end_offset = ? WHERE id = ?", (first_end, segment_id))
    cur = conn.execute(
        """
        INSERT INTO segments
            (document_id, code_id, start_offset, end_offset, memo, created_by, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            segment.document_id,
            segment.code_id,
            second_start,
            segment.end_offset,
            segment.memo,
            segment.created_by,
            segment.created_at,
        ),
    )
    conn.commit()
    return get_segment(conn, segment_id), get_segment(conn, cur.lastrowid)


def create_region(
    conn: sqlite3.Connection,
    document_id: int,
    page: int,
    text_offset: int,
    points: list[tuple[float, float]],
    created_by: str | None = None,
) -> Region:
    """Record a region outlined by `points`, in page fractions.

    The bounding box is derived and stored alongside, since ordering regions
    down a page and hit-testing them coarsely both want it.
    """
    xs = [float(x) for x, _ in points]
    ys = [float(y) for _, y in points]
    cur = conn.execute(
        """
        INSERT INTO regions
            (document_id, page, text_offset, x, y, width, height, points,
             created_by, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            document_id,
            page,
            text_offset,
            min(xs),
            min(ys),
            max(xs) - min(xs),
            max(ys) - min(ys),
            json.dumps([[float(x), float(y)] for x, y in points]),
            created_by,
            _now(),
        ),
    )
    conn.commit()
    return get_region(conn, cur.lastrowid)


def get_region(conn: sqlite3.Connection, region_id: int) -> Region | None:
    row = conn.execute("SELECT * FROM regions WHERE id = ?", (region_id,)).fetchone()
    return Region(**row) if row else None


def list_regions_for_document(conn: sqlite3.Connection, document_id: int) -> list[Region]:
    rows = conn.execute(
        "SELECT * FROM regions WHERE document_id = ? ORDER BY text_offset", (document_id,)
    ).fetchall()
    return [Region(**row) for row in rows]


def list_regions_for_page(
    conn: sqlite3.Connection, document_id: int, page: int
) -> list[Region]:
    rows = conn.execute(
        "SELECT * FROM regions WHERE document_id = ? AND page = ? ORDER BY text_offset",
        (document_id, page),
    ).fetchall()
    return [Region(**row) for row in rows]


def update_region_offset(
    conn: sqlite3.Connection, region_id: int, text_offset: int
) -> Region:
    conn.execute(
        "UPDATE regions SET text_offset = ? WHERE id = ?", (text_offset, region_id)
    )
    conn.commit()
    return get_region(conn, region_id)


def delete_region(conn: sqlite3.Connection, region_id: int) -> None:
    conn.execute("DELETE FROM regions WHERE id = ?", (region_id,))
    conn.commit()
