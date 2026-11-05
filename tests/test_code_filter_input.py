"""CodeFilterLineEdit: the keys that cycle the matched code."""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from openansho.ui.code_filter_input import CodeFilterLineEdit


def _make_input(qtbot):
    line_edit = CodeFilterLineEdit()
    qtbot.addWidget(line_edit)
    emitted = []
    line_edit.cyclePressed.connect(emitted.append)
    return line_edit, emitted


@pytest.mark.parametrize(
    ("key", "modifier", "direction"),
    [
        (Qt.Key_Up, Qt.NoModifier, -1),
        (Qt.Key_Down, Qt.NoModifier, 1),
        (Qt.Key_K, Qt.ControlModifier, -1),
        (Qt.Key_J, Qt.ControlModifier, 1),
        # The physical Control key on macOS arrives as Meta.
        (Qt.Key_K, Qt.MetaModifier, -1),
        (Qt.Key_J, Qt.MetaModifier, 1),
    ],
)
def test_key_cycles_the_matched_code(qtbot, key, modifier, direction):
    line_edit, emitted = _make_input(qtbot)
    line_edit.setText("foo")

    QTest.keyClick(line_edit, key, modifier)

    assert emitted == [direction]
    assert line_edit.text() == "foo"


def test_plain_j_and_k_are_still_typed(qtbot):
    line_edit, emitted = _make_input(qtbot)

    QTest.keyClicks(line_edit, "jk")

    assert emitted == []
    assert line_edit.text() == "jk"
