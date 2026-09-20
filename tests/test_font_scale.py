import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from openansho.ui import font_scale
from openansho.ui.main_window import (
    FONT_SCALE_KEY,
    SETTINGS_APPLICATION,
    SETTINGS_ORGANIZATION,
    MainWindow,
)
from openansho.ui.preferences_dialog import PreferencesDialog
from openansho.ui.shortcuts_dialog import SHORTCUT_SECTIONS


@pytest.fixture(autouse=True)
def _reset_font_scale(qapp):
    """Font scale is application-wide state stored in QSettings; keep each
    test from leaking its size into the rest of the suite."""
    settings = QSettings(SETTINGS_ORGANIZATION, SETTINGS_APPLICATION)
    settings.remove(FONT_SCALE_KEY)
    yield
    settings.remove(FONT_SCALE_KEY)
    font_scale.apply_font_scale(font_scale.DEFAULT_FONT_SCALE_PERCENT)


def _app_point_size() -> int:
    return QApplication.instance().font().pointSize()


def _expected_point_size(percent: int) -> int:
    return font_scale.scaled_font(percent).pointSize()


def test_defaults_to_one_hundred_percent(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)

    assert window.font_scale_percent == 100
    assert _app_point_size() == font_scale.base_font().pointSize()


def test_set_font_scale_resizes_the_application_font(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    enlarged = _expected_point_size(150)
    assert enlarged > font_scale.base_font().pointSize()

    window.set_font_scale(150)

    assert window.font_scale_percent == 150
    assert _app_point_size() == enlarged
    # The panes are polished by the window's stylesheet, which is the only
    # route by which an already-created widget picks up the new size.
    assert window.viewer.font().pointSize() == enlarged
    assert window.code_tree.font().pointSize() == enlarged


def test_increase_and_decrease_step_by_twenty_five_percent(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)

    window.increase_font_size()
    assert window.font_scale_percent == 125
    window.increase_font_size()
    assert window.font_scale_percent == 150

    window.decrease_font_size()
    window.decrease_font_size()
    assert window.font_scale_percent == 100
    assert _app_point_size() == font_scale.base_font().pointSize()


def test_scale_is_clamped_to_its_range(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)

    window.set_font_scale(10_000)
    assert window.font_scale_percent == font_scale.MAX_FONT_SCALE_PERCENT
    assert not window.increase_font_size_action.isEnabled()

    window.set_font_scale(1)
    assert window.font_scale_percent == font_scale.MIN_FONT_SCALE_PERCENT
    assert not window.decrease_font_size_action.isEnabled()


def test_scale_persists_across_windows(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    window.set_font_scale(175)

    reopened = MainWindow()
    qtbot.addWidget(reopened)

    assert reopened.font_scale_percent == 175
    assert _app_point_size() == _expected_point_size(175)
    assert reopened.viewer.font().pointSize() == _expected_point_size(175)


def test_settings_menu_shows_the_current_percent(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)

    assert window.font_size_action.text() == "Font Size: 100%"
    window.increase_font_size()
    assert window.font_size_action.text() == "Font Size: 125%"


def test_shortcuts_are_bound_to_the_menu_actions(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)

    increase = [s.toString() for s in window.increase_font_size_action.shortcuts()]
    decrease = [s.toString() for s in window.decrease_font_size_action.shortcuts()]

    assert "Ctrl++" in increase
    # Ctrl+= is the same physical key without Shift, which is what users press.
    assert "Ctrl+=" in increase
    assert "Ctrl+-" in decrease


def test_shortcuts_resize_the_font_from_the_text_pane(qtbot):
    """The window-wide eventFilter in MainWindow intercepts key presses, so
    check the Ctrl+/Ctrl- shortcuts still reach their actions. Keys have to go
    through the window handle — QTest's widget-level delivery skips the
    shortcut map that real key presses go through."""
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    window.viewer.setFocus()
    handle = window.windowHandle()

    QTest.keyClick(handle, Qt.Key_Equal, Qt.ControlModifier)
    assert window.font_scale_percent == 125

    QTest.keyClick(handle, Qt.Key_Plus, Qt.ControlModifier)
    assert window.font_scale_percent == 150

    QTest.keyClick(handle, Qt.Key_Minus, Qt.ControlModifier)
    QTest.keyClick(handle, Qt.Key_Minus, Qt.ControlModifier)
    assert window.font_scale_percent == 100


def test_preferences_dialog_spinbox_reports_changes(qtbot):
    dialog = PreferencesDialog(dark_mode=False, font_scale_percent=125)
    qtbot.addWidget(dialog)

    assert dialog.font_scale_spinbox.value() == 125

    with qtbot.waitSignal(dialog.fontScaleChanged) as blocker:
        dialog.font_scale_spinbox.setValue(150)
    assert blocker.args == [150]


def test_preferences_dialog_applies_the_scale_to_the_window(qtbot, monkeypatch):
    window = MainWindow()
    qtbot.addWidget(window)

    opened = {}

    def capture(self):
        opened["dialog"] = self
        return 0

    monkeypatch.setattr(PreferencesDialog, "exec", capture)
    window._on_show_preferences()
    opened["dialog"].font_scale_spinbox.setValue(200)

    assert window.font_scale_percent == 200


def test_shortcuts_popup_documents_the_font_size_keys():
    anywhere = dict(next(rows for title, rows in SHORTCUT_SECTIONS if title == "Anywhere"))
    assert "Ctrl++" in anywhere
    assert "Ctrl+-" in anywhere
