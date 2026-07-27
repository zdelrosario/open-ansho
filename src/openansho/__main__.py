import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from openansho.ui.main_window import MainWindow


def _icon_path() -> Path:
    # PyInstaller extracts bundled data files (see the Makefile's --add-data)
    # under sys._MEIPASS at runtime; fall back to the repo layout when running
    # from source.
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass) / "images" / "kanji_shou_app_icon.png"
    return Path(__file__).resolve().parent.parent.parent / "images" / "kanji_shou_app_icon.png"


def main() -> None:
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(str(_icon_path())))
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
