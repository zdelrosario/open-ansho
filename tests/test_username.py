import sysconfig
from pathlib import Path

from openansho import db, user
from openansho.ui.main_window import NO_USERNAME_TEXT, MainWindow


def test_read_username_missing_file_returns_none():
    assert user.read_username() is None


def test_write_then_read_username_roundtrips():
    user.write_username("alice")
    assert user.read_username() == "alice"


def test_username_file_lives_in_the_application_directory():
    user.write_username("alice")
    assert (user.application_directory() / ".openansho_user").exists()


def test_ensure_username_prompts_when_no_sidecar_file(qtbot, tmp_path, monkeypatch):
    window = MainWindow()
    qtbot.addWidget(window)
    window.create_project(tmp_path / "project.sqlite")

    monkeypatch.setattr(
        "openansho.ui.main_window.QInputDialog.getText",
        lambda *args, **kwargs: ("alice", True),
    )

    result = window._ensure_username()

    assert result == "alice"
    assert window.username == "alice"
    assert user.read_username() == "alice"


def test_ensure_username_reuses_stored_name_without_prompting(qtbot, tmp_path, monkeypatch):
    window = MainWindow()
    qtbot.addWidget(window)
    window.create_project(tmp_path / "project.sqlite")
    user.write_username("bob")

    def fail_if_called(*args, **kwargs):
        raise AssertionError("should not prompt when a username is already stored")

    monkeypatch.setattr("openansho.ui.main_window.QInputDialog.getText", fail_if_called)

    result = window._ensure_username()

    assert result == "bob"
    assert window.username == "bob"


def test_ensure_username_cancel_leaves_username_unset(qtbot, tmp_path, monkeypatch):
    window = MainWindow()
    qtbot.addWidget(window)
    window.create_project(tmp_path / "project.sqlite")

    monkeypatch.setattr(
        "openansho.ui.main_window.QInputDialog.getText",
        lambda *args, **kwargs: ("", False),
    )

    result = window._ensure_username()

    assert result is None
    assert window.username is None
    assert user.read_username() is None


def test_apply_segment_records_current_username(qtbot, tmp_path, monkeypatch):
    window = MainWindow()
    qtbot.addWidget(window)
    window.create_project(tmp_path / "project.sqlite")
    monkeypatch.setattr(
        "openansho.ui.main_window.QInputDialog.getText",
        lambda *args, **kwargs: ("alice", True),
    )
    window._ensure_username()

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
    window.create_project(tmp_path / "project.sqlite")
    monkeypatch.setattr(
        "openansho.ui.main_window.QInputDialog.getText",
        lambda *args, **kwargs: ("alice", True),
    )
    window._ensure_username()

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
    window.create_project(tmp_path / "project.sqlite")

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
    window.create_project(tmp_path / "project.sqlite")
    assert window.username_label.text() == NO_USERNAME_TEXT

    monkeypatch.setattr(
        "openansho.ui.main_window.QInputDialog.getText",
        lambda *args, **kwargs: ("alice", True),
    )
    window._ensure_username()

    assert window.username_label.text() == "alice"


def test_username_label_resets_to_placeholder_on_close_project(qtbot, tmp_path, monkeypatch):
    window = MainWindow()
    qtbot.addWidget(window)
    window.create_project(tmp_path / "project.sqlite")
    monkeypatch.setattr(
        "openansho.ui.main_window.QInputDialog.getText",
        lambda *args, **kwargs: ("alice", True),
    )
    window._ensure_username()
    assert window.username_label.text() == "alice"

    window.close_project()

    assert window.username_label.text() == NO_USERNAME_TEXT


def test_change_username_updates_username_and_sidecar_file(qtbot, monkeypatch):
    window = MainWindow()
    qtbot.addWidget(window)
    window.username = "alice"

    monkeypatch.setattr(
        "openansho.ui.main_window.QInputDialog.getText",
        lambda *args, **kwargs: ("bob", True),
    )

    window._on_change_username()

    assert window.username == "bob"
    assert window.username_label.text() == "bob"
    assert user.read_username() == "bob"


def test_change_username_prefills_the_current_username(qtbot, monkeypatch):
    window = MainWindow()
    qtbot.addWidget(window)
    window.username = "alice"

    captured = {}

    def fake_get_text(_parent, _title, _label, text=""):
        captured["prefilled"] = text
        return ("bob", True)

    monkeypatch.setattr("openansho.ui.main_window.QInputDialog.getText", fake_get_text)

    window._on_change_username()

    assert captured["prefilled"] == "alice"


def test_change_username_cancel_leaves_username_unchanged(qtbot, monkeypatch):
    window = MainWindow()
    qtbot.addWidget(window)
    window.username = "alice"
    user.write_username("alice")

    monkeypatch.setattr(
        "openansho.ui.main_window.QInputDialog.getText",
        lambda *args, **kwargs: ("", False),
    )

    window._on_change_username()

    assert window.username == "alice"
    assert user.read_username() == "alice"


def test_preferences_dialog_change_username_button_emits_signal(qtbot):
    from openansho.ui.preferences_dialog import PreferencesDialog

    dialog = PreferencesDialog(dark_mode=False, font_scale_percent=100)
    qtbot.addWidget(dialog)

    with qtbot.waitSignal(dialog.changeUsernameRequested, timeout=1000):
        dialog.change_username_button.click()


def test_installed_copy_stores_the_username_in_the_config_directory(tmp_path, monkeypatch):
    """A pip-installed copy must not write into site-packages, which can be
    read-only and is replaced wholesale on upgrade."""
    monkeypatch.setattr(user, "installed_in_site_packages", lambda: True)
    monkeypatch.setattr(user, "config_directory", lambda: tmp_path / "config")

    user.write_username("alice")

    assert (tmp_path / "config" / ".openansho_user").read_text() == "alice"
    assert user.read_username() == "alice"
    assert not (user.application_directory() / ".openansho_user").exists()


def test_library_path_detection_distinguishes_an_install_from_a_checkout():
    site_packages = Path(sysconfig.get_paths()["purelib"]).resolve()

    assert user._is_library_path(site_packages / "openansho") is True
    assert user._is_library_path(Path(__file__).resolve().parent) is False


def test_config_directory_follows_the_platform_convention(monkeypatch):
    monkeypatch.setattr(user.sys, "platform", "linux")
    monkeypatch.setenv("XDG_CONFIG_HOME", "/tmp/xdg")

    assert user.config_directory() == Path("/tmp/xdg/openansho")

    monkeypatch.setattr(user.sys, "platform", "darwin")

    assert user.config_directory() == Path.home() / "Library" / "Application Support" / "OpenAnsho"
