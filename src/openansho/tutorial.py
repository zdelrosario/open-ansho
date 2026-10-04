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

DOCUMENT_NAME = "01 Introduction.txt"
PDF_DOCUMENT_NAME = "02 PDF Coding.pdf"
# Every file the tutorial ships, in the order the documents are listed.
DOCUMENT_NAMES = (DOCUMENT_NAME, PDF_DOCUMENT_NAME)


def tutorial_file_path(name: str) -> Path:
    """Locate one of the tutorial's files, bundled or running from source.

    PyInstaller extracts the bundled copies (see the Makefile's --add-data and
    OpenAnsho.spec) under sys._MEIPASS at runtime; fall back to the files
    sitting next to this module when running from a source checkout.
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass) / "openansho" / name
    return Path(__file__).resolve().with_name(name)


def tutorial_text_path() -> Path:
    return tutorial_file_path(DOCUMENT_NAME)


def tutorial_pdf_path() -> Path:
    return tutorial_file_path(PDF_DOCUMENT_NAME)


def read_tutorial_text() -> str:
    return tutorial_text_path().read_text(encoding="utf-8")


def open_tutorial_project() -> sqlite3.Connection:
    """Open a throwaway in-memory project holding the tutorial documents."""
    from openansho import pdf_extract  # local: only this needs Qt

    conn = db.connect(":memory:")
    db.create_document(conn, DOCUMENT_NAME, read_tutorial_text())
    pdf_data = tutorial_pdf_path().read_bytes()
    db.create_document(
        conn,
        PDF_DOCUMENT_NAME,
        pdf_extract.pdf_text(pdf_data, PDF_DOCUMENT_NAME),
        kind=db.DOCUMENT_KIND_PDF,
        source_data=pdf_data,
    )
    return conn
