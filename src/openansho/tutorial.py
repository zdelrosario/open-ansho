"""The built-in tutorial project.

The app opens this project at startup so a first-time user has something to
code without importing anything first. Its database lives in memory rather
than in a .sqlite file, so whatever codebook the user builds while following
along is discarded on quit and the tutorial is fresh again on the next launch.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

from openansho import db

DOCUMENT_NAME = "tutorial.txt"


def tutorial_text_path() -> Path:
    """Locate the tutorial text, bundled or running from source.

    PyInstaller extracts the bundled copy (see the Makefile's --add-data and
    OpenAnsho.spec) under sys._MEIPASS at runtime; fall back to the file
    sitting next to this module when running from a source checkout.
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass) / "openansho" / DOCUMENT_NAME
    return Path(__file__).resolve().with_name(DOCUMENT_NAME)


def read_tutorial_text() -> str:
    return tutorial_text_path().read_text(encoding="utf-8")


def open_tutorial_project() -> sqlite3.Connection:
    """Open a throwaway in-memory project holding just the tutorial document."""
    conn = db.connect(":memory:")
    db.create_document(conn, DOCUMENT_NAME, read_tutorial_text())
    return conn
