"""A toggle button that is switched on reads as switched on, in either theme."""

import pytest
from PySide6.QtGui import QColor

from openansho.ui.main_window import MainWindow


def _background(button) -> QColor:
    # Just inside the 1px border at the bottom-right corner, clear of the label.
    return button.grab().toImage().pixelColor(button.width() - 3, button.height() - 3)


@pytest.mark.parametrize("dark", [False, True])
def test_a_checked_button_is_grey_and_an_unchecked_one_is_not(qtbot, dark):
    window = MainWindow()
    qtbot.addWidget(window)
    window.set_dark_mode(dark)
    window.show()
    pane = window.pdf_pane
    window.viewer_stack.setCurrentWidget(pane)  # styled only once it's showing

    pane.set_region_mode("freehand")
    on, off = _background(pane.freehand_button), _background(pane.rectangle_button)

    assert on != off
    assert on.red() == on.green() == on.blue()  # grey
    assert on.red() not in (0, 255)  # neither the black nor the white page


@pytest.mark.parametrize("dark", [False, True])
def test_the_insert_mode_button_turns_grey_while_on(qtbot, dark):
    window = MainWindow()
    qtbot.addWidget(window)
    window.set_dark_mode(dark)
    window.show()
    button = window.insert_mode_button

    before = _background(button)
    button.setChecked(True)
    after = _background(button)

    assert after != before
    assert after.red() == after.green() == after.blue()
    assert after.red() not in (0, 255)
