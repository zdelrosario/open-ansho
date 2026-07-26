import csv
import json

import pytest

from opencoder import db, reporting


@pytest.fixture
def conn():
    connection = db.connect(":memory:")
    yield connection
    connection.close()


def test_code_path_builds_ancestor_chain(conn):
    parent = db.create_code(conn, "Emotions")
    child = db.create_code(conn, "Frustration", parent_id=parent.id)

    codes_by_id = {c.id: c for c in db.list_codes(conn)}

    assert reporting.code_path(codes_by_id, parent.id) == "Emotions"
    assert reporting.code_path(codes_by_id, child.id) == "Emotions > Frustration"


def _sample_project(conn):
    doc = db.create_document(conn, "interview.txt", "It was frustrating but rewarding.")
    emotions = db.create_code(conn, "Emotions")
    frustration = db.create_code(conn, "Frustration", parent_id=emotions.id)
    reward = db.create_code(conn, "Reward")
    db.create_segment(conn, doc.id, frustration.id, 7, 18)  # "frustrating"
    db.create_segment(conn, doc.id, reward.id, 23, 32)  # "rewarding"
    return doc, emotions, frustration, reward


def test_export_segments_csv(conn, tmp_path):
    doc, emotions, frustration, reward = _sample_project(conn)
    out_path = tmp_path / "segments.csv"

    count = reporting.export_segments_csv(conn, out_path)

    assert count == 2
    with open(out_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    assert len(rows) == 2
    assert rows[0]["document"] == "interview.txt"
    assert rows[0]["code"] == "Emotions > Frustration"
    assert rows[0]["text"] == "frustrating"
    assert rows[1]["code"] == "Reward"
    assert rows[1]["text"] == "rewarding"


def test_export_segments_json(conn, tmp_path):
    _sample_project(conn)
    out_path = tmp_path / "segments.json"

    count = reporting.export_segments_json(conn, out_path)

    assert count == 2
    with open(out_path, encoding="utf-8") as f:
        rows = json.load(f)

    assert len(rows) == 2
    assert rows[0]["code"] == "Emotions > Frustration"
    assert rows[0]["start_offset"] == 7
    assert rows[0]["end_offset"] == 18


def test_code_frequency_counts_and_orders_by_count_desc(conn):
    doc = db.create_document(conn, "interview.txt", "aaa bbb ccc")
    frequent = db.create_code(conn, "Frequent")
    rare = db.create_code(conn, "Rare")
    db.create_segment(conn, doc.id, frequent.id, 0, 3)
    db.create_segment(conn, doc.id, frequent.id, 4, 7)
    db.create_segment(conn, doc.id, rare.id, 8, 11)

    rows = reporting.code_frequency(conn)

    assert rows[0]["path"] == "Frequent"
    assert rows[0]["count"] == 2
    assert rows[1]["path"] == "Rare"
    assert rows[1]["count"] == 1


def test_code_frequency_includes_codes_with_zero_segments(conn):
    db.create_code(conn, "Unused")

    rows = reporting.code_frequency(conn)

    assert len(rows) == 1
    assert rows[0]["count"] == 0
