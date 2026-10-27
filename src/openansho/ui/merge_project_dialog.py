from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QLabel,
    QMessageBox,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from openansho import project_merge
from openansho.db import Code
from openansho.project_merge import CodeMatch, MergedCode, MergePlan

CONFLICT_COLOR = QColor("#D32F2F")
CURRENT_SIDE = "current"
OTHER_SIDE = "other"
MERGED_SIDE = "merged"


def _conflict_tooltip(match: CodeMatch) -> str:
    reasons = []
    if match.parent_differs:
        reasons.append("a different parent")
    if match.description_differs:
        reasons.append("a different description")
    return (
        f"Has {' and '.join(reasons)} in the two projects. "
        "Check the version to keep in the merged project."
    )


def _merged_item_id(key: tuple[str, int]) -> str:
    """A merged code's key as item data: Qt hands a tuple back as a list."""
    return f"{key[0]}:{key[1]}"


class MergeProjectDialog(QDialog):
    """Shows both codebooks side by side and asks which version of each
    conflicting code to keep, with the codebook those choices produce in a
    third pane.

    A code whose parent or description differs between the projects is drawn
    in red with a checkbox on both sides; the two boxes act as a pair, so
    exactly one version is always chosen (this project's, by default).
    """

    def __init__(self, plan: MergePlan, other_name: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Merge Project")
        self.resize(1200, 600)
        self._plan = plan
        # Conflicting match, keyed by the other project's code id, -> the
        # checkable item on each side.
        self._conflict_items: dict[int, dict[str, QTreeWidgetItem]] = {}
        self._syncing = False
        self._other_name = other_name

        intro = QLabel(
            f"Merging <b>{other_name}</b> into this project. Codes found in only "
            "one project are kept, and every coded segment from both projects is "
            "kept for every user.<br>"
            f"<span style='color: {CONFLICT_COLOR.name()}'>Red</span> codes have a "
            "different parent or description in the two projects: check the "
            "version to keep."
        )
        intro.setWordWrap(True)

        self.current_tree = self._build_tree(CURRENT_SIDE, plan.current_codes)
        self.other_tree = self._build_tree(OTHER_SIDE, plan.other_codes)
        self.merged_tree = QTreeWidget()
        self.merged_tree.setHeaderLabels(["Code", "Description"])
        self.merged_tree.setColumnWidth(0, 220)
        self._rebuild_merged_tree()
        for tree in (self.current_tree, self.other_tree, self.merged_tree):
            tree.currentItemChanged.connect(
                lambda item, _prev, tree=tree: self._select_counterparts(tree, item)
            )
        self.current_tree.itemChanged.connect(self._on_item_changed)
        self.other_tree.itemChanged.connect(self._on_item_changed)

        trees = QGridLayout()
        trees.addWidget(QLabel("<b>This project</b>"), 0, 0)
        trees.addWidget(QLabel(f"<b>{other_name}</b>"), 0, 1)
        trees.addWidget(QLabel("<b>Merged result</b>"), 0, 2)
        trees.addWidget(self.current_tree, 1, 0)
        trees.addWidget(self.other_tree, 1, 1)
        trees.addWidget(self.merged_tree, 1, 2)

        self.summary_label = QLabel()
        self._update_summary()

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Merge")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addLayout(trees, stretch=1)
        layout.addWidget(self.summary_label)
        layout.addWidget(buttons)

    def _build_tree(self, side: str, codes: dict[int, Code]) -> QTreeWidget:
        tree = QTreeWidget()
        tree.setHeaderLabels(["Code", "Description"])
        tree.setColumnWidth(0, 220)
        items: dict[int, QTreeWidgetItem] = {}

        def add_children(parent_id: int | None, parent_item: QTreeWidgetItem | None) -> None:
            children = sorted(
                (code for code in codes.values() if code.parent_id == parent_id),
                key=lambda code: code.name.lower(),
            )
            for code in children:
                item = QTreeWidgetItem([code.name, code.description or ""])
                item.setData(0, Qt.UserRole, code.id)
                self._decorate(item, side, code)
                if parent_item is None:
                    tree.addTopLevelItem(item)
                else:
                    parent_item.addChild(item)
                items[code.id] = item
                add_children(code.id, item)

        add_children(None, None)
        tree.expandAll()
        return tree

    def _decorate(self, item: QTreeWidgetItem, side: str, code: Code) -> None:
        match = (
            self._plan.match_for_current(code.id)
            if side == CURRENT_SIDE
            else self._plan.match_for_other(code.id)
        )
        if match is None:
            return
        if match.is_conflict:
            red = QBrush(CONFLICT_COLOR)
            item.setForeground(0, red)
            item.setForeground(1, red)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(0, Qt.Checked if side == CURRENT_SIDE else Qt.Unchecked)
            tooltip = _conflict_tooltip(match)
            item.setToolTip(0, tooltip)
            item.setToolTip(1, tooltip)
            self._conflict_items.setdefault(match.other.id, {})[side] = item
        elif match.current is None or match.other is None:
            font = QFont(item.font(0))
            font.setItalic(True)
            item.setFont(0, font)
            item.setToolTip(
                0,
                "Only in this project."
                if side == CURRENT_SIDE
                else "Only in this project; it will be added.",
            )

    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self._syncing or column != 0:
            return
        for pair in self._conflict_items.values():
            side = next((s for s, candidate in pair.items() if candidate is item), None)
            if side is None:
                continue
            other_side = OTHER_SIDE if side == CURRENT_SIDE else CURRENT_SIDE
            counterpart_state = (
                Qt.Unchecked if item.checkState(0) == Qt.Checked else Qt.Checked
            )
            self._syncing = True
            try:
                pair[other_side].setCheckState(0, counterpart_state)
            finally:
                self._syncing = False
            self._update_summary()
            self._rebuild_merged_tree()
            return

    def _rebuild_merged_tree(self) -> None:
        tree = self.merged_tree
        selected = tree.currentItem()
        selected_id = selected.data(0, Qt.UserRole) if selected is not None else None
        tree.blockSignals(True)
        try:
            tree.clear()
            codes = project_merge.merged_codebook(self._plan, self.use_other_ids())
            children: dict[tuple | None, list[MergedCode]] = {}
            for code in codes:
                children.setdefault(code.parent, []).append(code)
            placed: set[tuple] = set()

            def add_children(parent_key, parent_item) -> None:
                for code in sorted(children.get(parent_key, []), key=lambda c: c.name.lower()):
                    item = self._merged_item(code)
                    if parent_item is None:
                        tree.addTopLevelItem(item)
                    else:
                        parent_item.addChild(item)
                    placed.add(code.key)
                    add_children(code.key, item)

            add_children(None, None)
            # Codes the choices nest inside each other never hang off a root;
            # show them at the top, in red, so the loop is visible.
            for code in sorted(codes, key=lambda c: c.name.lower()):
                if code.key in placed:
                    continue
                item = self._merged_item(code)
                red = QBrush(CONFLICT_COLOR)
                item.setForeground(0, red)
                item.setForeground(1, red)
                item.setToolTip(
                    0, "The chosen versions nest this code inside its own descendants."
                )
                tree.addTopLevelItem(item)
            tree.expandAll()
            if selected_id is not None:
                target = self._find_item(tree, selected_id)
                if target is not None:
                    tree.setCurrentItem(target)
        finally:
            tree.blockSignals(False)

    def _merged_item(self, code: MergedCode) -> QTreeWidgetItem:
        item = QTreeWidgetItem([code.name, code.description or ""])
        item.setData(0, Qt.UserRole, _merged_item_id(code.key))
        if code.key[0] == OTHER_SIDE:
            font = QFont(item.font(0))
            font.setItalic(True)
            item.setFont(0, font)
            item.setToolTip(0, f"Added from {self._other_name}.")
        elif code.source == OTHER_SIDE:
            item.setToolTip(0, f"Uses the version from {self._other_name}.")
        return item

    def _select_counterparts(self, tree: QTreeWidget, item: QTreeWidgetItem | None) -> None:
        """Select the code picked in `tree` in the other two panes as well."""
        if item is None:
            return
        data = item.data(0, Qt.UserRole)
        if tree is self.current_tree:
            match = self._plan.match_for_current(data)
        elif tree is self.other_tree:
            match = self._plan.match_for_other(data)
        else:
            side, code_id = data.split(":")
            match = (
                self._plan.match_for_current(int(code_id))
                if side == CURRENT_SIDE
                else self._plan.match_for_other(int(code_id))
            )
        if match is None:
            return
        merged_key = (
            (CURRENT_SIDE, match.current.id) if match.current else (OTHER_SIDE, match.other.id)
        )
        targets = {
            self.current_tree: match.current.id if match.current else None,
            self.other_tree: match.other.id if match.other else None,
            self.merged_tree: _merged_item_id(merged_key),
        }
        for target_tree, target_id in targets.items():
            if target_tree is tree:
                continue
            target = self._find_item(target_tree, target_id) if target_id is not None else None
            target_tree.blockSignals(True)
            try:
                if target is None:
                    target_tree.setCurrentItem(None)
                    target_tree.clearSelection()
                else:
                    target_tree.setCurrentItem(target)
                    target_tree.scrollToItem(target)
            finally:
                target_tree.blockSignals(False)

    @staticmethod
    def _find_item(tree: QTreeWidget, code_id: int | str) -> QTreeWidgetItem | None:
        stack = [tree.topLevelItem(i) for i in range(tree.topLevelItemCount())]
        while stack:
            item = stack.pop()
            if item.data(0, Qt.UserRole) == code_id:
                return item
            stack.extend(item.child(i) for i in range(item.childCount()))
        return None

    def _update_summary(self) -> None:
        added = sum(1 for match in self._plan.matches if match.current is None)
        conflicts = len(self._conflict_items)
        from_other = len(self.use_other_ids())
        self.summary_label.setText(
            f"{added} code(s) will be added. {conflicts} code(s) differ; "
            f"{from_other} will take the other project's version."
        )

    def set_use_other(self, other_code_id: int, use_other: bool) -> None:
        """Choose a conflicting code's version, as checking its box would."""
        pair = self._conflict_items[other_code_id]
        pair[OTHER_SIDE].setCheckState(0, Qt.Checked if use_other else Qt.Unchecked)

    def use_other_ids(self) -> set[int]:
        """Other-project ids of the conflicting codes whose other version was chosen."""
        return {
            other_id
            for other_id, pair in self._conflict_items.items()
            if pair[OTHER_SIDE].checkState(0) == Qt.Checked
        }

    def _on_accept(self) -> None:
        try:
            project_merge.check_choices(self._plan, self.use_other_ids())
        except project_merge.MergeError as exc:
            QMessageBox.warning(self, "Merge Project", str(exc))
            return
        self.accept()
