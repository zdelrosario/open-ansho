from PySide6.QtCore import Qt

from opencoder import db, user
from opencoder.ui.main_window import NO_USERNAME_TEXT, MainWindow


def _setup_project_with_document(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    project_path = tmp_path / "project.sqlite"
    window.create_project(project_path)

    doc_path = tmp_path / "doc.txt"
    doc_path.write_text("Hello frustrating world.", encoding="utf-8")
    window.import_document(doc_path)
    window.document_list.setCurrentRow(0)
    return window


def _add_existing_segment(window, code, start, end, username):
    """Simulate a segment already coded by someone else in a shared project
    file, without disturbing `window.username` (the active user)."""
    db.create_segment(
        window.conn, window._current_document_id, code.id, start, end, created_by=username
    )
    window._refresh_user_filter()
    window._refresh_codes()
    window._refresh_highlights()
    window._render_segments_panel()


def _checked_labels(combo):
    return {
        combo.model().item(i).text()
        for i in range(combo.model().rowCount())
        if combo.model().item(i).checkState() == Qt.Checked
    }


def _uncheck(combo, data_value):
    for i in range(combo.model().rowCount()):
        item = combo.model().item(i)
        if item.data() == data_value:
            item.setCheckState(Qt.Unchecked)
            return
    raise AssertionError(f"no combo item with data {data_value!r}")


def _check(combo, data_value):
    for i in range(combo.model().rowCount()):
        item = combo.model().item(i)
        if item.data() == data_value:
            item.setCheckState(Qt.Checked)
            return
    raise AssertionError(f"no combo item with data {data_value!r}")


def test_user_filter_defaults_to_only_the_active_user(qtbot, tmp_path):
    window = _setup_project_with_document(qtbot, tmp_path)
    code = window.add_code("Frustration")

    window.username = "alice"
    window.apply_segment(code.id, 6, 17)
    _add_existing_segment(window, code, 0, 5, "bob")

    assert _checked_labels(window.user_filter_combo) == {"alice"}


def test_user_filter_includes_placeholder_for_missing_username(qtbot, tmp_path):
    window = _setup_project_with_document(qtbot, tmp_path)
    code = window.add_code("Frustration")

    window.username = None
    window.apply_segment(code.id, 6, 17)

    assert _checked_labels(window.user_filter_combo) == {NO_USERNAME_TEXT}


def test_checking_another_user_adds_their_segments_to_the_list(qtbot, tmp_path):
    window = _setup_project_with_document(qtbot, tmp_path)
    code = window.add_code("Frustration")

    window.username = "alice"
    window.apply_segment(code.id, 6, 17)
    _add_existing_segment(window, code, 0, 5, "bob")

    window.code_tree.setCurrentItem(window.code_tree.topLevelItem(0))
    assert window.segment_list.count() == 1
    assert "alice" in window.segment_list.item(0).text()

    _check(window.user_filter_combo, "bob")

    assert window.segment_list.count() == 2


def test_default_filter_only_highlights_the_active_users_segments(qtbot, tmp_path):
    window = _setup_project_with_document(qtbot, tmp_path)
    code = window.add_code("Frustration")

    window.username = "alice"
    window.apply_segment(code.id, 6, 17)
    _add_existing_segment(window, code, 0, 5, "bob")

    assert len(window.viewer._code_highlights) == 1

    _check(window.user_filter_combo, "bob")

    assert len(window.viewer._code_highlights) == 2


def test_default_filter_only_counts_the_active_users_segments(qtbot, tmp_path):
    window = _setup_project_with_document(qtbot, tmp_path)
    code = window.add_code("Frustration")

    window.username = "alice"
    window.apply_segment(code.id, 6, 17)
    _add_existing_segment(window, code, 0, 5, "bob")

    item = window.code_tree.topLevelItem(0)
    assert item.text(1) == "1/1"

    _check(window.user_filter_combo, "bob")

    item = window.code_tree.topLevelItem(0)
    assert item.text(1) == "2/2"


def test_reopening_project_resets_filter_to_only_the_active_user(qtbot, tmp_path):
    window = _setup_project_with_document(qtbot, tmp_path)
    code = window.add_code("Frustration")
    window.username = "alice"
    window.apply_segment(code.id, 6, 17)
    _add_existing_segment(window, code, 0, 5, "bob")

    _check(window.user_filter_combo, "bob")
    assert _checked_labels(window.user_filter_combo) == {"alice", "bob"}

    project_path = window.project_path
    user.write_username(project_path, "alice")
    window._set_connection(*_reopen(project_path))
    window._ensure_username(project_path)

    assert _checked_labels(window.user_filter_combo) == {"alice"}


def _reopen(project_path):
    return db.connect(project_path), project_path


def test_highlight_bands_ranked_alphabetically_among_selected_users(qtbot, tmp_path):
    window = _setup_project_with_document(qtbot, tmp_path)
    code = window.add_code("Frustration")

    window.username = "alice"
    window.apply_segment(code.id, 0, 5)
    _add_existing_segment(window, code, 6, 17, "carol")
    _add_existing_segment(window, code, 18, 23, "bob")

    _check(window.user_filter_combo, "carol")
    _check(window.user_filter_combo, "bob")

    # Match each highlight back to the username via its start offset.
    starts_to_user = {6: "carol", 0: "alice", 18: "bob"}
    by_user = {starts_to_user[h.start]: h for h in window.viewer._code_highlights}

    assert by_user["alice"].band_index == 0
    assert by_user["bob"].band_index == 1
    assert by_user["carol"].band_index == 2
    assert all(h.band_count == 3 for h in window.viewer._code_highlights)


def test_highlight_band_count_shrinks_when_a_user_is_unchecked(qtbot, tmp_path):
    window = _setup_project_with_document(qtbot, tmp_path)
    code = window.add_code("Frustration")

    window.username = "alice"
    window.apply_segment(code.id, 0, 5)
    _add_existing_segment(window, code, 6, 17, "bob")
    _add_existing_segment(window, code, 18, 23, "carol")

    _check(window.user_filter_combo, "bob")
    _check(window.user_filter_combo, "carol")
    _uncheck(window.user_filter_combo, "bob")

    remaining = window.viewer._code_highlights
    assert len(remaining) == 2
    assert all(h.band_count == 2 for h in remaining)
    starts_to_user = {0: "alice", 18: "carol"}
    by_user = {starts_to_user[h.start]: h for h in remaining}
    assert by_user["alice"].band_index == 0
    assert by_user["carol"].band_index == 1


def test_single_selected_user_gets_full_height_band(qtbot, tmp_path):
    window = _setup_project_with_document(qtbot, tmp_path)
    code = window.add_code("Frustration")
    window.username = "alice"
    window.apply_segment(code.id, 6, 17)

    highlight = window.viewer._code_highlights[0]
    assert highlight.band_index == 0
    assert highlight.band_count == 1
