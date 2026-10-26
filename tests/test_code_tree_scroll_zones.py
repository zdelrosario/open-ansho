from PySide6.QtCore import QMimeData, QPoint, Qt
from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent
from PySide6.QtWidgets import QTreeWidgetItem

from openansho.ui.code_tree import CodeTreeWidget


def _scrollable_tree(qtbot, count=30):
    tree = CodeTreeWidget()
    qtbot.addWidget(tree)
    for i in range(count):
        item = QTreeWidgetItem([f"Code {i}"])
        item.setData(0, Qt.UserRole, i)
        tree.addTopLevelItem(item)
    tree.resize(200, 200)
    tree.show()
    qtbot.waitExposed(tree)
    return tree


def _enter_drag(tree):
    mime = tree.model().mimeData([tree.indexFromItem(tree.topLevelItem(0))])
    tree.dragEnterEvent(
        QDragEnterEvent(QPoint(10, 10), Qt.MoveAction, mime, Qt.LeftButton, Qt.NoModifier)
    )


def test_scroll_zone_is_two_codes_tall_during_drag(qtbot):
    tree = _scrollable_tree(qtbot)
    tree.verticalScrollBar().setValue(5)

    _enter_drag(tree)

    assert tree.scroll_zone_height() == 2 * tree.visualItemRect(tree.topLevelItem(5)).height()


def test_no_shading_outside_a_drag(qtbot):
    tree = _scrollable_tree(qtbot)
    tree.verticalScrollBar().setValue(5)

    assert tree.scroll_zone_shading() == (False, False)


def test_shading_drops_at_whichever_end_is_reached(qtbot):
    tree = _scrollable_tree(qtbot)
    bar = tree.verticalScrollBar()
    _enter_drag(tree)

    bar.setValue(bar.minimum())
    assert tree.scroll_zone_shading() == (False, True)

    bar.setValue(5)
    assert tree.scroll_zone_shading() == (True, True)

    bar.setValue(bar.maximum())
    assert tree.scroll_zone_shading() == (True, False)


def test_shading_clears_when_the_drag_leaves(qtbot):
    tree = _scrollable_tree(qtbot)
    tree.verticalScrollBar().setValue(5)
    _enter_drag(tree)

    tree.dragLeaveEvent(QDragLeaveEvent())

    assert tree.scroll_zone_shading() == (False, False)


def test_scroll_speeds_up_toward_the_edge_and_stops_outside_the_strips(qtbot):
    tree = _scrollable_tree(qtbot)
    tree.verticalScrollBar().setValue(50)
    _enter_drag(tree)
    zone = tree.scroll_zone_height()
    bottom = tree.viewport().rect().bottom() + 1

    assert tree.scroll_velocity(zone + 1) == 0
    assert tree.scroll_velocity(bottom - zone - 1) == 0
    assert tree.scroll_velocity(zone - 2) < 0
    assert tree.scroll_velocity(0) < tree.scroll_velocity(zone - 2)
    assert tree.scroll_velocity(bottom - zone + 2) > 0
    assert tree.scroll_velocity(bottom - 1) > tree.scroll_velocity(bottom - zone + 2)


def test_no_scrolling_into_an_end_already_reached(qtbot):
    tree = _scrollable_tree(qtbot)
    _enter_drag(tree)
    tree.verticalScrollBar().setValue(0)

    assert tree.scroll_velocity(0) == 0


def test_drag_scroll_moves_smoothly_and_re_aims_the_drop_target(qtbot, monkeypatch):
    tree = _scrollable_tree(qtbot)
    bar = tree.verticalScrollBar()
    bar.setValue(100)
    _enter_drag(tree)
    tree._last_drag_move = (QMimeData(), Qt.MoveAction, Qt.LeftButton, Qt.NoModifier)
    over_top_strip = tree.viewport().mapToGlobal(QPoint(10, 3))
    monkeypatch.setattr("openansho.ui.code_tree.QCursor.pos", lambda: over_top_strip)
    positions = []
    monkeypatch.setattr(tree, "dragMoveEvent", lambda event: positions.append(event.position().toPoint()))
    values = [bar.value()]
    bar.valueChanged.connect(values.append)
    tree._scroll_clock.start()
    tree._scroll_timer.start()

    qtbot.wait(200)

    steps = [before - after for before, after in zip(values, values[1:])]
    # Many small steps up, never a whole code's height in one jump.
    assert len(steps) >= 5
    assert all(0 < step < tree.code_row_height() for step in steps)
    assert positions and all(position == QPoint(10, 3) for position in positions)


def test_drag_scroll_stops_at_the_top(qtbot, monkeypatch):
    tree = _scrollable_tree(qtbot)
    bar = tree.verticalScrollBar()
    bar.setValue(5)
    _enter_drag(tree)
    over_top_strip = tree.viewport().mapToGlobal(QPoint(10, 3))
    monkeypatch.setattr("openansho.ui.code_tree.QCursor.pos", lambda: over_top_strip)
    tree._scroll_clock.start()
    tree._scroll_timer.start()

    qtbot.waitUntil(lambda: not tree._scroll_timer.isActive(), timeout=2000)

    assert bar.value() == bar.minimum()
    assert tree.scroll_zone_shading() == (False, True)
