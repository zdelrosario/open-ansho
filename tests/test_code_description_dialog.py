from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog

from openansho.ui.code_description_dialog import CodeDescriptionDialog


def test_ctrl_enter_accepts_dialog(qtbot):
    dialog = CodeDescriptionDialog("Old")
    qtbot.addWidget(dialog)

    qtbot.keyClick(dialog.editor, Qt.Key_Return, Qt.ControlModifier)

    assert dialog.result() == QDialog.Accepted
    assert dialog.description() == "Old"


def test_plain_enter_inserts_newline(qtbot):
    dialog = CodeDescriptionDialog("")
    qtbot.addWidget(dialog)

    qtbot.keyClicks(dialog.editor, "a")
    qtbot.keyClick(dialog.editor, Qt.Key_Return)
    qtbot.keyClicks(dialog.editor, "b")

    assert dialog.result() != QDialog.Accepted
    assert dialog.description() == "a\nb"


def test_long_description_wraps(qtbot):
    dialog = CodeDescriptionDialog("word " * 200)
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)

    layout = dialog.editor.document().firstBlock().layout()
    assert layout.lineCount() > 1
    assert dialog.editor.horizontalScrollBar().maximum() == 0
