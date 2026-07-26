from opencoder import db, user
from opencoder.ui.main_window import NO_USERNAME_TEXT, MainWindow


def test_read_username_missing_file_returns_none(tmp_path):
    project_path = tmp_path / "project.sqlite"
    assert user.read_username(project_path) is None


def test_write_then_read_username_roundtrips(tmp_path):
    project_path = tmp_path / "project.sqlite"
    user.write_username(project_path, "alice")
    assert user.read_username(project_path) == "alice"


def test_username_file_lives_next_to_project(tmp_path):
    project_path = tmp_path / "subdir" / "project.sqlite"
    project_path.parent.mkdir()
    user.write_username(project_path, "alice")
    assert (project_path.parent / ".opencoder_user").exists()


def test_ensure_username_prompts_when_no_sidecar_file(qtbot, tmp_path, monkeypatch):
    window = MainWindow()
    qtbot.addWidget(window)
    project_path = tmp_path / "project.sqlite"
    window.create_project(project_path)

    monkeypatch.setattr(
        "opencoder.ui.main_window.QInputDialog.getText",
        lambda *args, **kwargs: ("alice", True),
    )

    result = window._ensure_username(project_path)

    assert result == "alice"
    assert window.username == "alice"
    assert user.read_username(project_path) == "alice"


def test_ensure_username_reuses_stored_name_without_prompting(qtbot, tmp_path, monkeypatch):
    window = MainWindow()
    qtbot.addWidget(window)
    project_path = tmp_path / "project.sqlite"
    window.create_project(project_path)
    user.write_username(project_path, "bob")

    def fail_if_called(*args, **kwargs):
        raise AssertionError("should not prompt when a username is already stored")

    monkeypatch.setattr("opencoder.ui.main_window.QInputDialog.getText", fail_if_called)

    result = window._ensure_username(project_path)

    assert result == "bob"
    assert window.username == "bob"


def test_ensure_username_cancel_leaves_username_unset(qtbot, tmp_path, monkeypatch):
    window = MainWindow()
    qtbot.addWidget(window)
    project_path = tmp_path / "project.sqlite"
    window.create_project(project_path)

    monkeypatch.setattr(
        "opencoder.ui.main_window.QInputDialog.getText",
        lambda *args, **kwargs: ("", False),
    )

    result = window._ensure_username(project_path)

    assert result is None
    assert window.username is None
    assert user.read_username(project_path) is None


def test_apply_segment_records_current_username(qtbot, tmp_path, monkeypatch):
    window = MainWindow()
    qtbot.addWidget(window)
    project_path = tmp_path / "project.sqlite"
    window.create_project(project_path)
    monkeypatch.setattr(
        "opencoder.ui.main_window.QInputDialog.getText",
        lambda *args, **kwargs: ("alice", True),
    )
    window._ensure_username(project_path)

    doc_path = tmp_path / "doc.txt"
    doc_path.write_text("Hello world.", encoding="utf-8")
    window.import_document(doc_path)
    window.document_list.setCurrentRow(0)
    code = window.add_code("Greeting")
    window.apply_segment(code.id, 0, 5)

    segments = db.list_segments_for_document(window.conn, window._current_document_id)
    assert len(segments) == 1
    assert segments[0].created_by == "alice"


def test_segment_list_shows_document_name_and_username(qtbot, tmp_path, monkeypatch):
    window = MainWindow()
    qtbot.addWidget(window)
    project_path = tmp_path / "project.sqlite"
    window.create_project(project_path)
    monkeypatch.setattr(
        "opencoder.ui.main_window.QInputDialog.getText",
        lambda *args, **kwargs: ("alice", True),
    )
    window._ensure_username(project_path)

    doc_path = tmp_path / "doc.txt"
    doc_path.write_text("Hello frustrating world.", encoding="utf-8")
    window.import_document(doc_path)
    window.document_list.setCurrentRow(0)
    code = window.add_code("Frustration")
    window.apply_segment(code.id, 6, 17)

    window.code_tree.setCurrentItem(window.code_tree.topLevelItem(0))

    assert window.segment_list.count() == 1
    assert "[doc.txt, alice]" in window.segment_list.item(0).text()


def test_segment_list_shows_placeholder_for_segments_with_no_username(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    project_path = tmp_path / "project.sqlite"
    window.create_project(project_path)

    doc_path = tmp_path / "doc.txt"
    doc_path.write_text("Hello frustrating world.", encoding="utf-8")
    window.import_document(doc_path)
    window.document_list.setCurrentRow(0)
    code = window.add_code("Frustration")
    window.apply_segment(code.id, 6, 17)

    window.code_tree.setCurrentItem(window.code_tree.topLevelItem(0))

    assert f"[doc.txt, {NO_USERNAME_TEXT}]" in window.segment_list.item(0).text()


def test_username_label_shows_placeholder_when_no_username(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)

    assert window.username_label.text() == NO_USERNAME_TEXT


def test_username_label_updates_after_ensure_username(qtbot, tmp_path, monkeypatch):
    window = MainWindow()
    qtbot.addWidget(window)
    project_path = tmp_path / "project.sqlite"
    window.create_project(project_path)
    assert window.username_label.text() == NO_USERNAME_TEXT

    monkeypatch.setattr(
        "opencoder.ui.main_window.QInputDialog.getText",
        lambda *args, **kwargs: ("alice", True),
    )
    window._ensure_username(project_path)

    assert window.username_label.text() == "alice"


def test_username_label_resets_to_placeholder_on_close_project(qtbot, tmp_path, monkeypatch):
    window = MainWindow()
    qtbot.addWidget(window)
    project_path = tmp_path / "project.sqlite"
    window.create_project(project_path)
    monkeypatch.setattr(
        "opencoder.ui.main_window.QInputDialog.getText",
        lambda *args, **kwargs: ("alice", True),
    )
    window._ensure_username(project_path)
    assert window.username_label.text() == "alice"

    window.close_project()

    assert window.username_label.text() == NO_USERNAME_TEXT
