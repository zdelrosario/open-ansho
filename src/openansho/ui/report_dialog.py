from __future__ import annotations

from PySide6.QtWidgets import QDialog, QTableWidget, QTableWidgetItem, QVBoxLayout

NO_USERNAME_TEXT = "(NO USERNAME)"


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


class CodeUserFrequencyDialog(QDialog):
    def __init__(self, rows: list[dict], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Code/User Frequency Report")
        self.resize(500, 300)

        self.table = QTableWidget(len(rows), 4)
        self.table.setHorizontalHeaderLabels(["Code", "Parent", "User", "Segments"])
        for row_index, row in enumerate(rows):
            self.table.setItem(row_index, 0, QTableWidgetItem(row["code"]))
            self.table.setItem(row_index, 1, QTableWidgetItem(row["parent"]))
            self.table.setItem(
                row_index, 2, QTableWidgetItem(row["username"] or NO_USERNAME_TEXT)
            )
            self.table.setItem(row_index, 3, QTableWidgetItem(str(row["count"])))
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.resizeColumnsToContents()

        layout = QVBoxLayout(self)
        layout.addWidget(self.table)
