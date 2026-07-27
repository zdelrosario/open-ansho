from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from openansho.ui.main_window import MainWindow


def test_question_mark_in_viewer_opens_shortcuts_dialog(qtbot, tmp_path, monkeypatch):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    window.create_project(tmp_path / "project.sqlite")

    captured = {}

    class FakeDialog:
        def __init__(self, parent=None):
            captured["parent"] = parent

        def exec(self):
            captured["executed"] = True

    monkeypatch.setattr("openansho.ui.main_window.ShortcutsDialog", FakeDialog)

    window.viewer.setFocus()
    qtbot.waitUntil(lambda: window.viewer.hasFocus())
    QTest.keyClick(window.viewer, Qt.Key_Question, Qt.ShiftModifier)

    assert captured["executed"] is True
    assert captured["parent"] is window


def test_on_show_shortcuts_opens_dialog(qtbot, monkeypatch):
    window = MainWindow()
    qtbot.addWidget(window)

    captured = {}
    monkeypatch.setattr(
        "openansho.ui.main_window.ShortcutsDialog",
        lambda parent=None: type("D", (), {"exec": lambda self: captured.setdefault("executed", True)})(),
    )

    window._on_show_shortcuts()

    assert captured["executed"] is True
