from __future__ import annotations

from PySide6.QtWidgets import QDialog, QTableWidget, QTableWidgetItem, QVBoxLayout


class CodeFrequencyDialog(QDialog):
    def __init__(self, rows: list[dict], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Code Frequency Report")
        self.resize(400, 300)

        self.table = QTableWidget(len(rows), 2)
        self.table.setHorizontalHeaderLabels(["Code", "Segments"])
        for row_index, row in enumerate(rows):
            self.table.setItem(row_index, 0, QTableWidgetItem(row["path"]))
            self.table.setItem(row_index, 1, QTableWidgetItem(str(row["count"])))
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.resizeColumnsToContents()

        layout = QVBoxLayout(self)
        layout.addWidget(self.table)
