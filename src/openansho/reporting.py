"""Export and aggregate reporting over a project's coded segments.

These functions operate directly on a sqlite3.Connection so they can
be used from the UI, a future CLI, or tests without any Qt dependency.
"""

from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path

from openansho import db
from openansho.db import Code

CSV_FIELDNAMES = [
    "document",
    "code",
    "start_offset",
    "end_offset",
    "text",
    "memo",
    "username",
    "created_at",
]


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
                    "username": segment.created_by or "",
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


def code_user_frequency(conn: sqlite3.Connection) -> list[dict]:
    """One row per (code, user) pair: the code, its parent, the username, and
    how many segments that user has coded with that code across the dataset."""
    codes_by_id = {code.id: code for code in db.list_codes(conn)}

    counts: dict[tuple[int, str], int] = {}
    for code_id in codes_by_id:
        for segment in db.list_segments_for_code(conn, code_id):
            key = (code_id, segment.created_by or "")
            counts[key] = counts.get(key, 0) + 1

    rows = []
    for (code_id, username), count in counts.items():
        code = codes_by_id[code_id]
        parent = codes_by_id.get(code.parent_id) if code.parent_id else None
        rows.append(
            {
                "code": code.name,
                "parent": parent.name if parent else "",
                "username": username,
                "count": count,
            }
        )
    rows.sort(key=lambda row: (row["code"], row["username"]))
    return rows


CODE_FREQUENCY_CSV_FIELDNAMES = ["code", "count"]
CODE_USER_FREQUENCY_CSV_FIELDNAMES = ["code", "parent", "username", "count"]


def export_code_frequency_csv(conn: sqlite3.Connection, path: str | Path) -> int:
    rows = code_frequency(conn)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CODE_FREQUENCY_CSV_FIELDNAMES)
        writer.writeheader()
        for row in rows:
            writer.writerow({"code": row["path"], "count": row["count"]})
    return len(rows)


def export_code_frequency_json(conn: sqlite3.Connection, path: str | Path) -> int:
    rows = code_frequency(conn)
    export_rows = [{"code": row["path"], "count": row["count"]} for row in rows]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(export_rows, f, indent=2)
    return len(rows)


def export_code_user_frequency_csv(conn: sqlite3.Connection, path: str | Path) -> int:
    rows = code_user_frequency(conn)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CODE_USER_FREQUENCY_CSV_FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def export_code_user_frequency_json(conn: sqlite3.Connection, path: str | Path) -> int:
    rows = code_user_frequency(conn)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2)
    return len(rows)
