"""Export and aggregate reporting over a project's coded segments.

These functions operate directly on a sqlite3.Connection so they can
be used from the UI, a future CLI, or tests without any Qt dependency.
"""

from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path

from opencoder import db
from opencoder.db import Code

CSV_FIELDNAMES = ["document", "code", "start_offset", "end_offset", "text", "memo", "created_at"]


def code_path(codes_by_id: dict[int, Code], code_id: int) -> str:
    parts = []
    current = codes_by_id.get(code_id)
    while current is not None:
        parts.append(current.name)
        current = codes_by_id.get(current.parent_id) if current.parent_id else None
    return " > ".join(reversed(parts))


def _segment_rows(conn: sqlite3.Connection) -> list[dict]:
    codes_by_id = {code.id: code for code in db.list_codes(conn)}
    documents = db.list_documents(conn)

    rows = []
    for document in documents:
        for segment in db.list_segments_for_document(conn, document.id):
            rows.append(
                {
                    "document": document.name,
                    "code": code_path(codes_by_id, segment.code_id),
                    "start_offset": segment.start_offset,
                    "end_offset": segment.end_offset,
                    "text": document.content[segment.start_offset : segment.end_offset],
                    "memo": segment.memo or "",
                    "created_at": segment.created_at,
                }
            )
    rows.sort(key=lambda row: (row["document"], row["start_offset"]))
    return rows


def export_segments_csv(conn: sqlite3.Connection, path: str | Path) -> int:
    rows = _segment_rows(conn)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def export_segments_json(conn: sqlite3.Connection, path: str | Path) -> int:
    rows = _segment_rows(conn)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2)
    return len(rows)


def code_frequency(conn: sqlite3.Connection) -> list[dict]:
    codes_by_id = {code.id: code for code in db.list_codes(conn)}
    rows = [
        {
            "code_id": code_id,
            "path": code_path(codes_by_id, code_id),
            "count": len(db.list_segments_for_code(conn, code_id)),
        }
        for code_id in codes_by_id
    ]
    rows.sort(key=lambda row: (-row["count"], row["path"]))
    return rows
