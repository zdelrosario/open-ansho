import csv

from opencoder.ui.main_window import (
    PROJECT_SECTION_LABEL_CLOSED,
    PROJECT_SECTION_LABEL_OPEN,
    MainWindow,
)


def test_export_actions_disabled_without_project(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)

    assert not window.export_csv_action.isEnabled()
    assert not window.export_json_action.isEnabled()
    assert not window.code_frequency_action.isEnabled()
    assert not window.export_code_frequency_menu.isEnabled()


def test_project_section_label_reflects_project_state(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)

    assert window.project_section_action.text() == PROJECT_SECTION_LABEL_CLOSED
    assert not window.project_section_action.isEnabled()

    window.create_project(tmp_path / "project.sqlite")

    assert window.project_section_action.text() == PROJECT_SECTION_LABEL_OPEN
    assert not window.project_section_action.isEnabled()


def test_export_actions_enabled_with_project(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.create_project(tmp_path / "project.sqlite")

    assert window.export_csv_action.isEnabled()
    assert window.export_json_action.isEnabled()
    assert window.code_frequency_action.isEnabled()
    assert window.export_code_frequency_menu.isEnabled()


def test_on_export_csv_writes_file(qtbot, tmp_path, monkeypatch):
    window = MainWindow()
    qtbot.addWidget(window)
    window.create_project(tmp_path / "project.sqlite")
    doc_path = tmp_path / "doc.txt"
    doc_path.write_text("Hello frustrating world.", encoding="utf-8")
    window.import_document(doc_path)
    window.document_list.setCurrentRow(0)
    code = window.add_code("Frustration")
    window.apply_segment(code.id, 6, 17)

    out_path = tmp_path / "out.csv"
    monkeypatch.setattr(
        "opencoder.ui.main_window.QFileDialog.getSaveFileName",
        lambda *args, **kwargs: (str(out_path), ""),
    )
    monkeypatch.setattr(
        "opencoder.ui.main_window.QMessageBox.information",
        lambda *args, **kwargs: None,
    )

    window._on_export_csv()

    with open(out_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    assert rows[0]["text"] == "frustrating"


def test_on_export_code_frequency_csv_writes_file(qtbot, tmp_path, monkeypatch):
    window = MainWindow()
    qtbot.addWidget(window)
    window.create_project(tmp_path / "project.sqlite")
    doc_path = tmp_path / "doc.txt"
    doc_path.write_text("Hello frustrating world.", encoding="utf-8")
    window.import_document(doc_path)
    window.document_list.setCurrentRow(0)
    code = window.add_code("Frustration")
    window.apply_segment(code.id, 6, 17)

    out_path = tmp_path / "out.csv"
    monkeypatch.setattr(
        "opencoder.ui.main_window.QFileDialog.getSaveFileName",
        lambda *args, **kwargs: (str(out_path), ""),
    )
    monkeypatch.setattr(
        "opencoder.ui.main_window.QMessageBox.information",
        lambda *args, **kwargs: None,
    )

    window._on_export_code_frequency_csv()

    with open(out_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert rows == [{"code": "Frustration", "count": "1"}]


def test_on_export_code_user_frequency_csv_writes_file(qtbot, tmp_path, monkeypatch):
    window = MainWindow()
    qtbot.addWidget(window)
    window.create_project(tmp_path / "project.sqlite")
    window.username = "alice"
    doc_path = tmp_path / "doc.txt"
    doc_path.write_text("Hello frustrating world.", encoding="utf-8")
    window.import_document(doc_path)
    window.document_list.setCurrentRow(0)
    code = window.add_code("Frustration")
    window.apply_segment(code.id, 6, 17)

    out_path = tmp_path / "out.csv"
    monkeypatch.setattr(
        "opencoder.ui.main_window.QFileDialog.getSaveFileName",
        lambda *args, **kwargs: (str(out_path), ""),
    )
    monkeypatch.setattr(
        "opencoder.ui.main_window.QMessageBox.information",
        lambda *args, **kwargs: None,
    )

    window._on_export_code_user_frequency_csv()

    with open(out_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert rows == [{"code": "Frustration", "parent": "", "username": "alice", "count": "1"}]


def test_on_code_frequency_report_builds_dialog_with_rows(qtbot, tmp_path, monkeypatch):
    window = MainWindow()
    qtbot.addWidget(window)
    window.create_project(tmp_path / "project.sqlite")
    window.add_code("Frustration")

    captured = {}

    class FakeDialog:
        def __init__(self, rows, parent=None):
            captured["rows"] = rows

        def exec(self):
            captured["executed"] = True

    monkeypatch.setattr("opencoder.ui.main_window.CodeFrequencyDialog", FakeDialog)

    window._on_code_frequency_report()

    assert captured["executed"] is True
    assert captured["rows"][0]["path"] == "Frustration"
    assert captured["rows"][0]["count"] == 0
