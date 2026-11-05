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
NAVIGATION_DOCUMENT_NAME = "03 Navigation.txt"
# Every file the tutorial ships, in the order the documents are listed.
DOCUMENT_NAMES = (DOCUMENT_NAME, PDF_DOCUMENT_NAME, NAVIGATION_DOCUMENT_NAME)

# The coder whose work comes pre-loaded in the tutorial: the introduction
# coded the way it asks the user to code it, so the user can check theirs
# against it by turning this coder on in the Coded Segments user filter. The
# filter starts out showing only the active user, so these stay hidden until
# then.
TUTORIAL_USERNAME = "Tutorial"

# The pre-loaded codebook, as (name, parent name) in creation order. It
# mirrors the one the introduction asks the user to build ([instructions] >
# [selection], [action]; [explanations] > [general], [shortcuts]) under names
# of its own: codes are shared by every coder, so reusing the tutorial's names
# would hand the user codes the text tells them to create. The code filter
# matches substrings, so none of these may contain anything the tutorials have
# the user type -- the code names, "ins", or the lone "c" of 03 Navigation --
# which rules out the letter c altogether.
TUTORIAL_CODES = (
    ("To Do", None),
    ("Highlight", "To Do"),
    ("Keystroke", "To Do"),
    ("Overview", None),
    ("Features", "Overview"),
    ("Hotkeys", "Overview"),
)

# The introduction's coding steps, as (passage, code name). Each passage is
# the text inside one of its "(...)" prompts and appears exactly once.
TUTORIAL_SEGMENTS = (
    ("First, try selecting this sentence using your mouse.", "To Do"),
    ("Select this sentence, and press the Spacebar.", "To Do"),
    ("Select this segment", "Highlight"),
)


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
    introduction = db.create_document(conn, DOCUMENT_NAME, read_tutorial_text())
    pdf_data = tutorial_pdf_path().read_bytes()
    db.create_document(
        conn,
        PDF_DOCUMENT_NAME,
        pdf_extract.pdf_text(pdf_data, PDF_DOCUMENT_NAME),
        kind=db.DOCUMENT_KIND_PDF,
        source_data=pdf_data,
    )
    db.create_document(
        conn,
        NAVIGATION_DOCUMENT_NAME,
        tutorial_file_path(NAVIGATION_DOCUMENT_NAME).read_text(encoding="utf-8"),
    )
    _seed_tutorial_coding(conn, introduction)
    return conn


def _seed_tutorial_coding(conn: sqlite3.Connection, introduction: db.Document) -> None:
    """Add the Tutorial coder's codebook and its coding of the introduction.

    The codes are created without colors; `MainWindow.open_tutorial_project`
    assigns them, since the palette lives in the UI.
    """
    code_ids: dict[str, int] = {}
    for name, parent_name in TUTORIAL_CODES:
        parent_id = code_ids[parent_name] if parent_name is not None else None
        code_ids[name] = db.create_code(conn, name, parent_id=parent_id).id
    for passage, code_name in TUTORIAL_SEGMENTS:
        start = introduction.content.index(passage)
        db.create_segment(
            conn,
            introduction.id,
            code_ids[code_name],
            start,
            start + len(passage),
            created_by=TUTORIAL_USERNAME,
        )
