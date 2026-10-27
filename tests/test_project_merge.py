import sqlite3

import pytest
from PySide6.QtCore import Qt

from openansho import db, project_merge
from openansho.ui.main_window import MainWindow
from openansho.ui.merge_project_dialog import CONFLICT_COLOR, MergeProjectDialog


@pytest.fixture
def projects():
    current = db.connect(":memory:")
    other = db.connect(":memory:")
    yield current, other
    current.close()
    other.close()


def _codes_by_name(conn):
    return {code.name: code for code in db.list_codes(conn)}


def test_identical_codes_are_not_conflicts(projects):
    current, other = projects
    for conn in projects:
        parent = db.create_code(conn, "Emotion", description="Feelings")
        db.create_code(conn, "Joy", parent_id=parent.id)

    plan = project_merge.plan_merge(current, other)

    assert plan.conflicts == []
    assert all(match.current and match.other for match in plan.matches)


def test_different_parent_or_description_is_a_conflict(projects):
    current, other = projects
    db.create_code(current, "Emotion")
    db.create_code(current, "Context")
    db.create_code(current, "Joy", parent_id=_codes_by_name(current)["Emotion"].id)
    db.create_code(current, "Place", description="Where it happened")

    db.create_code(other, "Emotion")
    db.create_code(other, "Context")
    db.create_code(other, "Joy", parent_id=_codes_by_name(other)["Context"].id)
    db.create_code(other, "Place", description="Location")

    plan = project_merge.plan_merge(current, other)
    conflicts = {match.name: match for match in plan.conflicts}

    assert set(conflicts) == {"Joy", "Place"}
    assert conflicts["Joy"].parent_differs and not conflicts["Joy"].description_differs
    assert conflicts["Place"].description_differs and not conflicts["Place"].parent_differs


def test_codes_only_in_other_are_added_under_their_parent(projects):
    current, other = projects
    db.create_code(current, "Emotion")
    emotion = db.create_code(other, "Emotion")
    db.create_code(other, "Anger", parent_id=emotion.id)

    plan = project_merge.plan_merge(current, other)
    result = project_merge.apply_merge(current, other, plan, set())

    codes = _codes_by_name(current)
    assert result.codes_added == 1
    assert codes["Anger"].parent_id == codes["Emotion"].id


def test_chosen_version_decides_parent_and_description(projects):
    current, other = projects
    for conn in projects:
        db.create_code(conn, "Emotion")
        db.create_code(conn, "Context")
    db.create_code(current, "Joy", parent_id=_codes_by_name(current)["Emotion"].id)
    db.create_code(current, "Place", description="Where")
    db.create_code(other, "Joy", parent_id=_codes_by_name(other)["Context"].id)
    db.create_code(other, "Place", description="Location")

    plan = project_merge.plan_merge(current, other)
    other_joy = _codes_by_name(other)["Joy"].id
    result = project_merge.apply_merge(current, other, plan, {other_joy})

    codes = _codes_by_name(current)
    assert codes["Joy"].parent_id == codes["Context"].id
    assert codes["Place"].description == "Where"
    assert result.codes_updated == 1
    assert len(codes) == 4


def test_mixed_choices_that_nest_codes_in_a_loop_are_refused(projects):
    current, other = projects
    a = db.create_code(current, "A")
    db.create_code(current, "B", parent_id=a.id)
    b = db.create_code(other, "B")
    db.create_code(other, "A", parent_id=b.id)

    plan = project_merge.plan_merge(current, other)
    other_a = _codes_by_name(other)["A"].id

    with pytest.raises(project_merge.MergeError):
        project_merge.apply_merge(current, other, plan, {other_a})
    # Taking the other version of both is a consistent codebook.
    project_merge.apply_merge(current, other, plan, {other_a, b.id})
    codes = _codes_by_name(current)
    assert codes["B"].parent_id is None
    assert codes["A"].parent_id == codes["B"].id


def test_segments_are_the_superset_and_keep_every_user(projects):
    current, other = projects
    for conn in projects:
        db.create_document(conn, "interview.txt", "hello world, goodbye")
        db.create_code(conn, "Greeting")
    doc = db.list_documents(current)[0].id
    code = _codes_by_name(current)["Greeting"].id
    db.create_segment(current, doc, code, 0, 5, created_by="alice")

    other_doc = db.list_documents(other)[0].id
    other_code = _codes_by_name(other)["Greeting"].id
    db.create_segment(other, other_doc, other_code, 0, 5, created_by="alice")
    db.create_segment(other, other_doc, other_code, 0, 5, created_by="bob")
    db.create_segment(other, other_doc, other_code, 13, 20, memo="bye", created_by="bob")

    plan = project_merge.plan_merge(current, other)
    result = project_merge.apply_merge(current, other, plan, set())

    segments = db.list_all_segments(current)
    assert result.segments_added == 2
    assert result.documents_added == 0
    assert {(s.start_offset, s.end_offset, s.created_by) for s in segments} == {
        (0, 5, "alice"),
        (0, 5, "bob"),
        (13, 20, "bob"),
    }
    assert next(s for s in segments if s.start_offset == 13).memo == "bye"


def test_documents_with_different_text_are_added_separately(projects):
    current, other = projects
    db.create_document(current, "notes.txt", "version one")
    db.create_document(other, "notes.txt", "version two!")
    db.create_document(other, "extra.txt", "only here")
    code = db.create_code(other, "Topic")
    db.create_segment(other, db.list_documents(other)[0].id, code.id, 0, 7, created_by="bob")

    plan = project_merge.plan_merge(current, other)
    result = project_merge.apply_merge(current, other, plan, set(), other_label="theirs")

    names = {document.name: document for document in db.list_documents(current)}
    assert set(names) == {"notes.txt", "notes.txt (theirs)", "extra.txt"}
    assert result.documents_renamed == [("notes.txt", "notes.txt (theirs)")]
    [segment] = db.list_all_segments(current)
    assert segment.document_id == names["notes.txt (theirs)"].id


def test_new_pdf_documents_bring_their_regions(projects):
    current, other = projects
    doc = db.create_document(other, "paper.pdf", "text\n▭\n", kind=db.DOCUMENT_KIND_PDF)
    db.create_region(other, doc.id, 0, 5, [(0.1, 0.1), (0.5, 0.1), (0.5, 0.4)], created_by="bob")

    plan = project_merge.plan_merge(current, other)
    project_merge.apply_merge(current, other, plan, set())

    [merged] = db.list_documents(current)
    [region] = db.list_regions_for_document(current, merged.id)
    assert merged.is_pdf
    assert region.text_offset == 5
    assert region.outline() == [(0.1, 0.1), (0.5, 0.1), (0.5, 0.4)]


def test_connect_copy_leaves_the_file_untouched(tmp_path):
    path = tmp_path / "old.sqlite"
    raw = sqlite3.connect(path)
    raw.execute(
        "CREATE TABLE codes (id INTEGER PRIMARY KEY, name TEXT NOT NULL, "
        "parent_id INTEGER, color TEXT, created_at TEXT NOT NULL)"
    )
    raw.execute("INSERT INTO codes (name, created_at) VALUES ('Old', 'then')")
    raw.commit()
    raw.close()
    before = path.read_bytes()

    copy = db.connect_copy(path)
    copy.execute("INSERT INTO codes (name, created_at) VALUES ('New', 'now')")
    copy.commit()

    assert [code.name for code in db.list_codes(copy)] == ["Old", "New"]
    copy.close()
    assert path.read_bytes() == before


def test_dialog_checkboxes_pick_one_version(qtbot, projects):
    current, other = projects
    db.create_code(current, "Place", description="Where")
    db.create_code(current, "Same")
    db.create_code(other, "Place", description="Location")
    db.create_code(other, "Same")
    db.create_code(other, "New")
    plan = project_merge.plan_merge(current, other)

    dialog = MergeProjectDialog(plan, "other.sqlite")
    qtbot.addWidget(dialog)
    other_place = _codes_by_name(other)["Place"].id
    current_item = dialog._find_item(dialog.current_tree, _codes_by_name(current)["Place"].id)
    other_item = dialog._find_item(dialog.other_tree, other_place)
    same_item = dialog._find_item(dialog.current_tree, _codes_by_name(current)["Same"].id)

    assert current_item.foreground(0).color() == CONFLICT_COLOR
    assert same_item.foreground(0).color() != CONFLICT_COLOR
    assert same_item.data(0, Qt.CheckStateRole) is None
    assert dialog.use_other_ids() == set()

    other_item.setCheckState(0, Qt.Checked)
    assert current_item.checkState(0) == Qt.Unchecked
    assert dialog.use_other_ids() == {other_place}

    current_item.setCheckState(0, Qt.Checked)
    assert other_item.checkState(0) == Qt.Unchecked
    assert dialog.use_other_ids() == set()


def test_window_merge_project_refreshes_and_recolors(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.create_project(tmp_path / "mine.sqlite")
    emotion = window.add_code("Emotion")

    other = db.connect(":memory:")
    other_emotion = db.create_code(other, "Emotion", color="#123456", color_class="#123456")
    db.create_code(other, "Joy", parent_id=other_emotion.id, color="#abcdef", color_class="#123456")
    doc = db.create_document(other, "talk.txt", "so happy")
    db.create_segment(other, doc.id, _codes_by_name(other)["Joy"].id, 3, 8, created_by="bob")

    plan = project_merge.plan_merge(window.conn, other)
    window.merge_project(other, plan, set())

    codes = _codes_by_name(window.conn)
    assert codes["Joy"].parent_id == emotion.id
    assert codes["Joy"].color_class == emotion.color_class
    assert window.document_list.count() == 1
    assert len(db.list_all_segments(window.conn)) == 1
    assert window.merge_project_action.isEnabled()


def test_merged_codebook_follows_choices(projects):
    current, other = projects
    for conn in projects:
        db.create_code(conn, "Emotion")
        db.create_code(conn, "Context")
    db.create_code(current, "Joy", parent_id=_codes_by_name(current)["Emotion"].id)
    db.create_code(other, "Joy", parent_id=_codes_by_name(other)["Context"].id, description="Glad")
    db.create_code(other, "Anger", parent_id=_codes_by_name(other)["Emotion"].id)
    plan = project_merge.plan_merge(current, other)
    current_codes, other_codes = _codes_by_name(current), _codes_by_name(other)

    def by_name(use_other):
        return {code.name: code for code in project_merge.merged_codebook(plan, use_other)}

    kept = by_name(set())
    assert kept["Joy"].parent == ("current", current_codes["Emotion"].id)
    assert kept["Joy"].description is None and kept["Joy"].source == "current"
    assert kept["Anger"].key == ("other", other_codes["Anger"].id)
    assert kept["Anger"].parent == ("current", current_codes["Emotion"].id)

    taken = by_name({other_codes["Joy"].id})
    assert taken["Joy"].parent == ("current", current_codes["Context"].id)
    assert taken["Joy"].description == "Glad" and taken["Joy"].source == "other"


def test_dialog_merged_pane_tracks_checkboxes(qtbot, projects):
    current, other = projects
    for conn in projects:
        db.create_code(conn, "Emotion")
        db.create_code(conn, "Context")
    db.create_code(current, "Joy", parent_id=_codes_by_name(current)["Emotion"].id)
    db.create_code(other, "Joy", parent_id=_codes_by_name(other)["Context"].id)
    db.create_code(other, "Anger")
    plan = project_merge.plan_merge(current, other)
    dialog = MergeProjectDialog(plan, "other.sqlite")
    qtbot.addWidget(dialog)
    current_codes, other_codes = _codes_by_name(current), _codes_by_name(other)

    def merged_parent_of_joy():
        item = dialog._find_item(dialog.merged_tree, f"current:{current_codes['Joy'].id}")
        return item.parent().text(0)

    assert merged_parent_of_joy() == "Emotion"
    assert dialog._find_item(dialog.merged_tree, f"other:{other_codes['Anger'].id}")

    dialog.set_use_other(other_codes["Joy"].id, True)
    assert merged_parent_of_joy() == "Context"

    # Picking a code in the merged pane picks its counterparts too.
    dialog.merged_tree.setCurrentItem(
        dialog._find_item(dialog.merged_tree, f"current:{current_codes['Joy'].id}")
    )
    assert dialog.current_tree.currentItem().text(0) == "Joy"
    assert dialog.other_tree.currentItem().data(0, Qt.UserRole) == other_codes["Joy"].id


def test_dialog_merged_pane_shows_a_loop_in_red(qtbot, projects):
    current, other = projects
    a = db.create_code(current, "A")
    db.create_code(current, "B", parent_id=a.id)
    b = db.create_code(other, "B")
    db.create_code(other, "A", parent_id=b.id)
    plan = project_merge.plan_merge(current, other)
    dialog = MergeProjectDialog(plan, "other.sqlite")
    qtbot.addWidget(dialog)

    dialog.set_use_other(_codes_by_name(other)["A"].id, True)

    tree = dialog.merged_tree
    tops = [tree.topLevelItem(i) for i in range(tree.topLevelItemCount())]
    assert sorted(item.text(0) for item in tops) == ["A", "B"]
    assert all(item.foreground(0).color() == CONFLICT_COLOR for item in tops)
