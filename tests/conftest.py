import os

# Creating and tearing down ~140 real on-screen windows in quick succession
# crashes/segfaults the native Cocoa platform plugin on macOS. Tests don't
# need a visible window, so default to the offscreen QPA platform; this must
# run before pytest-qt's session-scoped `qapp` fixture constructs the
# QApplication. Explicitly set QT_QPA_PLATFORM beforehand to override.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from openansho import user


@pytest.fixture
def write_pdf(qapp):
    """Factory writing a small real PDF: `write_pdf(path, [["line"], ...])`.

    One list of text lines per page, each page also carrying a solid
    rectangle standing in for a figure — the sort of non-text area a region
    gets drawn over. Built with Qt's own PDF writer so the fixture needs no
    dependency the app doesn't already have; `qapp` is required because
    painting text needs the font database.
    """

    from PySide6.QtGui import QColor, QFont, QImage, QPageSize, QPainter, QPdfWriter

    def _write_pdf(path, pages):
        writer = QPdfWriter(str(path))
        writer.setPageSize(QPageSize(QPageSize.A4))
        writer.setResolution(72)
        painter = QPainter(writer)
        font = QFont("Helvetica")
        font.setPointSize(12)
        painter.setFont(font)
        figure = QImage(160, 100, QImage.Format_RGB32)
        figure.fill(QColor("steelblue"))
        for index, lines in enumerate(pages):
            if index:
                writer.newPage()
            y = 80
            for line in lines:
                painter.drawText(50, y, line)
                y += 24
            painter.drawImage(50, y + 20, figure)
        painter.end()
        return path

    return _write_pdf


@pytest.fixture(autouse=True)
def _isolate_username_file(tmp_path, monkeypatch):
    """The real .openansho_user sidecar lives next to the installed app, one
    per machine — redirect it into each test's own tmp_path so tests never
    read or clobber the developer's actual username file on disk. The
    site-packages branch is pinned off as well, so a test run against an
    installed copy of the package stays inside tmp_path too."""
    monkeypatch.setattr(user, "application_directory", lambda: tmp_path)
    monkeypatch.setattr(user, "installed_in_site_packages", lambda: False)
