from PySide6.QtCore import Qt

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


def test_user_filter_defaults_to_all_users_checked(qtbot, tmp_path):
    window = _setup_project_with_document(qtbot, tmp_path)
    code = window.add_code("Frustration")

    window.username = "alice"
    window.apply_segment(code.id, 6, 17)
    window.username = "bob"
    window.apply_segment(code.id, 0, 5)

    assert _checked_labels(window.user_filter_combo) == {"alice", "bob"}


def test_user_filter_includes_placeholder_for_missing_username(qtbot, tmp_path):
    window = _setup_project_with_document(qtbot, tmp_path)
    code = window.add_code("Frustration")

    window.username = None
    window.apply_segment(code.id, 6, 17)

    assert _checked_labels(window.user_filter_combo) == {NO_USERNAME_TEXT}


def test_unchecking_user_filters_segment_list(qtbot, tmp_path):
    window = _setup_project_with_document(qtbot, tmp_path)
    code = window.add_code("Frustration")

    window.username = "alice"
    window.apply_segment(code.id, 6, 17)
    window.username = "bob"
    window.apply_segment(code.id, 0, 5)

    window.code_tree.setCurrentItem(window.code_tree.topLevelItem(0))
    assert window.segment_list.count() == 2

    _uncheck(window.user_filter_combo, "bob")

    assert window.segment_list.count() == 1
    assert "alice" in window.segment_list.item(0).text()


def test_unchecking_user_filters_viewer_highlights(qtbot, tmp_path):
    window = _setup_project_with_document(qtbot, tmp_path)
    code = window.add_code("Frustration")

    window.username = "alice"
    window.apply_segment(code.id, 6, 17)
    window.username = "bob"
    window.apply_segment(code.id, 0, 5)

    assert len(window.viewer._code_highlights) == 2

    _uncheck(window.user_filter_combo, "bob")

    assert len(window.viewer._code_highlights) == 1


def test_unchecking_user_filters_codebook_counts(qtbot, tmp_path):
    window = _setup_project_with_document(qtbot, tmp_path)
    code = window.add_code("Frustration")

    window.username = "alice"
    window.apply_segment(code.id, 6, 17)
    window.username = "bob"
    window.apply_segment(code.id, 0, 5)

    item = window.code_tree.topLevelItem(0)
    assert item.text(1) == "2/2"

    _uncheck(window.user_filter_combo, "bob")

    item = window.code_tree.topLevelItem(0)
    assert item.text(1) == "1/1"


def test_reopening_project_resets_filter_to_all_checked(qtbot, tmp_path):
    window = _setup_project_with_document(qtbot, tmp_path)
    code = window.add_code("Frustration")
    window.username = "alice"
    window.apply_segment(code.id, 6, 17)
    window.username = "bob"
    window.apply_segment(code.id, 0, 5)

    _uncheck(window.user_filter_combo, "bob")
    assert _checked_labels(window.user_filter_combo) == {"alice"}

    project_path = window.project_path
    window._set_connection(*_reopen(project_path))

    assert _checked_labels(window.user_filter_combo) == {"alice", "bob"}


def _reopen(project_path):
    from opencoder import db

    return db.connect(project_path), project_path
