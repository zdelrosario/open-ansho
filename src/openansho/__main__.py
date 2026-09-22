import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from openansho.ui.main_window import MainWindow


ICON_FILENAME = "kanji_shou_app_icon.png"


def _icon_path() -> Path:
    # Three layouts to cover: PyInstaller extracts bundled data files (see the
    # Makefile's --add-data) under sys._MEIPASS; an installed wheel carries the
    # icon inside the package (see pyproject's force-include); a source checkout
    # has it at the repo root, which is where the Makefile reads it from.
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass) / "images" / ICON_FILENAME
    packaged = Path(__file__).resolve().parent / ICON_FILENAME
    if packaged.exists():
        return packaged
    return Path(__file__).resolve().parent.parent.parent / "images" / ICON_FILENAME


def main() -> None:
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(str(_icon_path())))
    window = MainWindow()
    # Start in the built-in tutorial so the app opens onto something codeable;
    # it's an in-memory project, so it costs the user nothing to abandon.
    window.open_tutorial_project()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
