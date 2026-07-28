import csv
import json

import pytest

from openansho import db, reporting


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
    db.create_segment(conn, doc.id, frustration.id, 7, 18, created_by="alice")  # "frustrating"
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
    assert rows[0]["username"] == "alice"
    assert rows[1]["code"] == "Reward"
    assert rows[1]["text"] == "rewarding"
    assert rows[1]["username"] == ""


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
    assert rows[0]["username"] == "alice"


def test_export_treats_simultaneously_applied_codes_as_separate_rows(conn, tmp_path):
    """Two codes applied to the same span (simultaneous coding) are two
    separate segment rows in the DB, and must export as two separate rows
    rather than being merged or having one overwrite the other."""
    doc = db.create_document(conn, "interview.txt", "It was frustrating but rewarding.")
    frustration = db.create_code(conn, "Frustration")
    setting = db.create_code(conn, "Setting")
    db.create_segment(conn, doc.id, frustration.id, 7, 18, created_by="alice")
    db.create_segment(conn, doc.id, setting.id, 7, 18, created_by="alice")  # same span

    out_path = tmp_path / "segments.csv"
    count = reporting.export_segments_csv(conn, out_path)

    assert count == 2
    with open(out_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    assert len(rows) == 2
    assert {row["code"] for row in rows} == {"Frustration", "Setting"}
    assert all(row["text"] == "frustrating" for row in rows)


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


def test_code_user_frequency_groups_by_code_and_user(conn):
    doc, emotions, frustration, reward = _sample_project(conn)
    db.create_segment(conn, doc.id, frustration.id, 0, 3, created_by="alice")
    db.create_segment(conn, doc.id, frustration.id, 4, 7, created_by="bob")

    rows = reporting.code_user_frequency(conn)
    by_user = {(row["code"], row["username"]): row for row in rows}

    frustration_alice = by_user[("Frustration", "alice")]
    assert frustration_alice["parent"] == "Emotions"
    assert frustration_alice["count"] == 2

    frustration_bob = by_user[("Frustration", "bob")]
    assert frustration_bob["count"] == 1

    reward_unassigned = by_user[("Reward", "")]
    assert reward_unassigned["parent"] == ""
    assert reward_unassigned["count"] == 1


def test_export_code_frequency_csv(conn, tmp_path):
    doc = db.create_document(conn, "interview.txt", "aaa bbb ccc")
    frequent = db.create_code(conn, "Frequent")
    rare = db.create_code(conn, "Rare")
    db.create_segment(conn, doc.id, frequent.id, 0, 3)
    db.create_segment(conn, doc.id, rare.id, 8, 11)
    out_path = tmp_path / "code_frequency.csv"

    count = reporting.export_code_frequency_csv(conn, out_path)

    assert count == 2
    with open(out_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert rows == [
        {"code": "Frequent", "count": "1"},
        {"code": "Rare", "count": "1"},
    ]


def test_export_code_frequency_json(conn, tmp_path):
    doc = db.create_document(conn, "interview.txt", "aaa bbb ccc")
    frequent = db.create_code(conn, "Frequent")
    db.create_segment(conn, doc.id, frequent.id, 0, 3)
    out_path = tmp_path / "code_frequency.json"

    count = reporting.export_code_frequency_json(conn, out_path)

    assert count == 1
    with open(out_path, encoding="utf-8") as f:
        rows = json.load(f)
    assert rows == [{"code": "Frequent", "count": 1}]


def test_export_code_user_frequency_csv(conn, tmp_path):
    doc, emotions, frustration, reward = _sample_project(conn)
    out_path = tmp_path / "code_user_frequency.csv"

    count = reporting.export_code_user_frequency_csv(conn, out_path)

    assert count == 2
    with open(out_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    by_code = {row["code"]: row for row in rows}
    assert by_code["Frustration"]["parent"] == "Emotions"
    assert by_code["Frustration"]["username"] == "alice"
    assert by_code["Reward"]["username"] == ""


def test_export_code_user_frequency_json(conn, tmp_path):
    doc, emotions, frustration, reward = _sample_project(conn)
    out_path = tmp_path / "code_user_frequency.json"

    count = reporting.export_code_user_frequency_json(conn, out_path)

    assert count == 2
    with open(out_path, encoding="utf-8") as f:
        rows = json.load(f)
    by_code = {row["code"]: row for row in rows}
    assert by_code["Frustration"]["username"] == "alice"
