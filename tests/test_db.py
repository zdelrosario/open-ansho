import sqlite3

import pytest

from openansho import db


@pytest.fixture
def conn():
    connection = db.connect(":memory:")
    yield connection
    connection.close()


def test_create_and_get_document(conn):
    doc = db.create_document(conn, "interview_01.txt", "Hello world.")
    assert doc.id is not None
    assert doc.name == "interview_01.txt"
    assert doc.content == "Hello world."

    fetched = db.get_document(conn, doc.id)
    assert fetched == doc


def test_list_documents_ordered(conn):
    first = db.create_document(conn, "a.txt", "a")
    second = db.create_document(conn, "b.txt", "b")

    docs = db.list_documents(conn)
    assert [d.id for d in docs] == [first.id, second.id]


def test_create_nested_codes(conn):
    parent = db.create_code(conn, "Emotions")
    child = db.create_code(conn, "Frustration", parent_id=parent.id, color="#ff0000")

    assert child.parent_id == parent.id
    assert child.color == "#ff0000"

    codes = db.list_codes(conn)
    assert {c.id for c in codes} == {parent.id, child.id}


def test_rename_code(conn):
    code = db.create_code(conn, "Frustration")

    renamed = db.rename_code(conn, code.id, "Frustration (renamed)")

    assert renamed.id == code.id
    assert renamed.name == "Frustration (renamed)"
    assert db.get_code(conn, code.id).name == "Frustration (renamed)"


def test_set_code_description(conn):
    code = db.create_code(conn, "Frustration")
    assert code.description is None

    updated = db.set_code_description(conn, code.id, "Expressions of frustration.")

    assert updated.description == "Expressions of frustration."
    assert db.get_code(conn, code.id).description == "Expressions of frustration."


def test_set_code_parent_nests_a_top_level_code(conn):
    parent = db.create_code(conn, "Emotions")
    child = db.create_code(conn, "Frustration")

    updated = db.set_code_parent(conn, child.id, parent.id)

    assert updated.parent_id == parent.id


def test_set_code_parent_none_makes_it_top_level(conn):
    parent = db.create_code(conn, "Emotions")
    child = db.create_code(conn, "Frustration", parent_id=parent.id)

    updated = db.set_code_parent(conn, child.id, None)

    assert updated.parent_id is None


def test_delete_code_reparents_children_to_grandparent(conn):
    grandparent = db.create_code(conn, "Emotions")
    parent = db.create_code(conn, "Frustration", parent_id=grandparent.id)
    child = db.create_code(conn, "Anger", parent_id=parent.id)

    db.delete_code(conn, parent.id)

    assert db.get_code(conn, parent.id) is None
    assert db.get_code(conn, child.id).parent_id == grandparent.id


def test_delete_code_makes_children_root_when_no_grandparent(conn):
    parent = db.create_code(conn, "Emotions")
    child = db.create_code(conn, "Frustration", parent_id=parent.id)

    db.delete_code(conn, parent.id)

    assert db.get_code(conn, parent.id) is None
    assert db.get_code(conn, child.id).parent_id is None


def test_delete_code_removes_its_own_segments(conn):
    doc = db.create_document(conn, "doc.txt", "Hello world.")
    code = db.create_code(conn, "Greeting")
    db.create_segment(conn, doc.id, code.id, 0, 5)

    db.delete_code(conn, code.id)

    assert db.list_segments_for_document(conn, doc.id) == []


def test_delete_code_leaves_siblings_and_other_codes_alone(conn):
    parent = db.create_code(conn, "Emotions")
    keep_child = db.create_code(conn, "Anger", parent_id=parent.id)
    other = db.create_code(conn, "Reward")

    db.delete_code(conn, parent.id)

    assert db.get_code(conn, keep_child.id).parent_id is None
    assert db.get_code(conn, other.id) is not None


def test_create_segment_links_document_and_code(conn):
    doc = db.create_document(conn, "interview_01.txt", "Hello world.")
    code = db.create_code(conn, "Greeting")

    segment = db.create_segment(conn, doc.id, code.id, 0, 5, memo="opening line")

    assert segment.document_id == doc.id
    assert segment.code_id == code.id
    assert segment.memo == "opening line"


def test_create_segment_rejects_invalid_offsets(conn):
    doc = db.create_document(conn, "interview_01.txt", "Hello world.")
    code = db.create_code(conn, "Greeting")

    with pytest.raises(ValueError):
        db.create_segment(conn, doc.id, code.id, 5, 5)


def test_list_segments_for_document_ordered_by_offset(conn):
    doc = db.create_document(conn, "interview_01.txt", "Hello world, it's me.")
    code = db.create_code(conn, "Greeting")

    db.create_segment(conn, doc.id, code.id, 13, 21)
    db.create_segment(conn, doc.id, code.id, 0, 5)

    segments = db.list_segments_for_document(conn, doc.id)
    assert [s.start_offset for s in segments] == [0, 13]


def test_list_segments_for_code(conn):
    doc = db.create_document(conn, "interview_01.txt", "Hello world.")
    code_a = db.create_code(conn, "Greeting")
    code_b = db.create_code(conn, "Other")

    db.create_segment(conn, doc.id, code_a.id, 0, 5)
    db.create_segment(conn, doc.id, code_b.id, 6, 11)

    segments = db.list_segments_for_code(conn, code_a.id)
    assert len(segments) == 1
    assert segments[0].code_id == code_a.id


def test_segment_requires_existing_document_and_code(conn):
    with pytest.raises(sqlite3.IntegrityError):
        db.create_segment(conn, document_id=999, code_id=999, start_offset=0, end_offset=1)


def test_delete_segment(conn):
    doc = db.create_document(conn, "interview_01.txt", "Hello world.")
    code = db.create_code(conn, "Greeting")
    segment = db.create_segment(conn, doc.id, code.id, 0, 5)

    db.delete_segment(conn, segment.id)

    assert db.get_segment(conn, segment.id) is None
    assert db.list_segments_for_document(conn, doc.id) == []


def test_count_segments_by_code_across_all_documents(conn):
    doc_a = db.create_document(conn, "a.txt", "Hello world.")
    doc_b = db.create_document(conn, "b.txt", "Hello again.")
    code_a = db.create_code(conn, "Greeting")
    code_b = db.create_code(conn, "Other")

    db.create_segment(conn, doc_a.id, code_a.id, 0, 5)
    db.create_segment(conn, doc_b.id, code_a.id, 0, 5)
    db.create_segment(conn, doc_a.id, code_b.id, 6, 11)

    counts = db.count_segments_by_code(conn)
    assert counts == {code_a.id: 2, code_b.id: 1}


def test_count_segments_by_code_for_one_document(conn):
    doc_a = db.create_document(conn, "a.txt", "Hello world.")
    doc_b = db.create_document(conn, "b.txt", "Hello again.")
    code = db.create_code(conn, "Greeting")

    db.create_segment(conn, doc_a.id, code.id, 0, 5)
    db.create_segment(conn, doc_b.id, code.id, 0, 5)

    assert db.count_segments_by_code(conn, doc_a.id) == {code.id: 1}


def test_count_segments_by_code_omits_uncoded_codes(conn):
    code = db.create_code(conn, "Unused")

    assert db.count_segments_by_code(conn) == {}
