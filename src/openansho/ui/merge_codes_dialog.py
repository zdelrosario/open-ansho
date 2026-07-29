from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QMessageBox,
    QVBoxLayout,
)


class MergeCodesDialog(QDialog):
    """Prompts for two distinct codes: one to keep, one to merge away."""

    def __init__(
        self,
        options: list[tuple[int, str]],
        default_merge_id: int | None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Merge Codes")

        self.keep_combo = QComboBox()
        self.merge_combo = QComboBox()
        for code_id, label in options:
            self.keep_combo.addItem(label, code_id)
            self.merge_combo.addItem(label, code_id)

        if default_merge_id is not None:
            merge_index = self.merge_combo.findData(default_merge_id)
            if merge_index != -1:
                self.merge_combo.setCurrentIndex(merge_index)
            keep_index = next(
                (
                    i
                    for i in range(self.keep_combo.count())
                    if self.keep_combo.itemData(i) != default_merge_id
                ),
                0,
            )
            self.keep_combo.setCurrentIndex(keep_index)

        form = QFormLayout()
        form.addRow("Keep this code:", self.keep_combo)
        form.addRow("Merge this code:", self.merge_combo)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def _on_accept(self) -> None:
        if self.keep_id() == self.merge_id():
            QMessageBox.warning(
                self, "Merge Codes", "Choose two different codes to merge."
            )
            return
        self.accept()

    def keep_id(self) -> int:
        return self.keep_combo.currentData()

    def merge_id(self) -> int:
        return self.merge_combo.currentData()
