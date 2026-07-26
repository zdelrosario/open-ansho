"""SQLite-backed data access layer for OpenCoder projects.

A project is a single .sqlite file containing documents, a codebook
(codes, possibly nested), and the coded segments linking the two.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS codes (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    parent_id INTEGER REFERENCES codes(id) ON DELETE CASCADE,
    color TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS segments (
    id INTEGER PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    code_id INTEGER NOT NULL REFERENCES codes(id) ON DELETE CASCADE,
    start_offset INTEGER NOT NULL,
    end_offset INTEGER NOT NULL,
    memo TEXT,
    created_at TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class Document:
    id: int
    name: str
    content: str
    created_at: str


@dataclass(frozen=True)
class Code:
    id: int
    name: str
    parent_id: int | None
    color: str | None
    created_at: str


@dataclass(frozen=True)
class Segment:
    id: int
    document_id: int
    code_id: int
    start_offset: int
    end_offset: int
    memo: str | None
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
    conn.commit()


def create_document(conn: sqlite3.Connection, name: str, content: str) -> Document:
    cur = conn.execute(
        "INSERT INTO documents (name, content, created_at) VALUES (?, ?, ?)",
        (name, content, _now()),
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


def create_code(
    conn: sqlite3.Connection,
    name: str,
    parent_id: int | None = None,
    color: str | None = None,
) -> Code:
    cur = conn.execute(
        "INSERT INTO codes (name, parent_id, color, created_at) VALUES (?, ?, ?, ?)",
        (name, parent_id, color, _now()),
    )
    conn.commit()
    return get_code(conn, cur.lastrowid)


def get_code(conn: sqlite3.Connection, code_id: int) -> Code | None:
    row = conn.execute("SELECT * FROM codes WHERE id = ?", (code_id,)).fetchone()
    return Code(**row) if row else None


def list_codes(conn: sqlite3.Connection) -> list[Code]:
    rows = conn.execute("SELECT * FROM codes ORDER BY id").fetchall()
    return [Code(**row) for row in rows]


def create_segment(
    conn: sqlite3.Connection,
    document_id: int,
    code_id: int,
    start_offset: int,
    end_offset: int,
    memo: str | None = None,
) -> Segment:
    if end_offset <= start_offset:
        raise ValueError("end_offset must be greater than start_offset")
    cur = conn.execute(
        """
        INSERT INTO segments
            (document_id, code_id, start_offset, end_offset, memo, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (document_id, code_id, start_offset, end_offset, memo, _now()),
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
