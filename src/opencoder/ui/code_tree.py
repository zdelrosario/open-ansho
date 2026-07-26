from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QAbstractItemView, QTreeWidget


class CodeTreeWidget(QTreeWidget):
    """A QTreeWidget that reports reparenting after an internal drag-drop."""

    codeReparented = Signal(int, object)  # (code_id, new_parent_code_id_or_None)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.InternalMove)

    def dropEvent(self, event) -> None:
        selected = self.selectedItems()
        dragged_item = selected[0] if selected else self.currentItem()

        super().dropEvent(event)

        if dragged_item is None:
            return
        code_id = dragged_item.data(0, Qt.UserRole)
        parent_item = dragged_item.parent()
        new_parent_id = parent_item.data(0, Qt.UserRole) if parent_item is not None else None
        self.codeReparented.emit(code_id, new_parent_id)
