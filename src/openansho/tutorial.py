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
CODEBOOK_DOCUMENT_NAME = "03 Codebook.txt"
NAVIGATION_DOCUMENT_NAME = "04 Navigation.txt"
# Every file the tutorial ships, in the order the documents are listed.
DOCUMENT_NAMES = (
    DOCUMENT_NAME,
    PDF_DOCUMENT_NAME,
    CODEBOOK_DOCUMENT_NAME,
    NAVIGATION_DOCUMENT_NAME,
)

# The coder whose work comes pre-loaded in the tutorial: each document's
# coding steps done the way it asks the user to do them, so the user can check
# theirs against it by turning this coder on in the Coded Segments user
# filter. The filter starts out showing only the active user, so these stay
# hidden until then.
TUTORIAL_USERNAME = "Tutorial"

# The pre-loaded codebook, as (name, parent name) in creation order. It
# mirrors the ones the tutorials ask the user to build under names of its own:
# the introduction's ([instructions] > [selection], [action]; [explanations] >
# [general], [shortcuts]), and 03 Codebook's as it stands once its steps are
# done ([test] > [test1], with [test2] merged into [test1]). Codes are shared
# by every coder, so reusing the tutorials' names would hand the user codes
# the text tells them to create. The code filter matches substrings, so none
# of these may contain anything the tutorials have the user type -- the code
# names, "ins", or the lone "c" of 03 Codebook and 04 Navigation -- which
# rules out the letter c altogether.
TUTORIAL_CODES = (
    ("To Do", None),
    ("Highlight", "To Do"),
    ("Keystroke", "To Do"),
    ("Overview", None),
    ("Features", "Overview"),
    ("Hotkeys", "Overview"),
    ("Trial", None),
    ("Trial 1", "Trial"),
)

# The tutorials' coding steps, as (document name, passage, code name). Each
# passage is the text inside one of a document's "(...)" prompts. A passage is
# looked for after the end of the previous one in the same document, so the
# steps of a document are listed in reading order and a prompt that repeats
# -- 03 Codebook's three "(this segment)" -- is coded once per occurrence.
TUTORIAL_SEGMENTS = (
    (DOCUMENT_NAME, "First, try selecting this sentence using your mouse.", "To Do"),
    (DOCUMENT_NAME, "Select this sentence, and press the Spacebar.", "To Do"),
    (DOCUMENT_NAME, "Select this segment", "Highlight"),
    # [test1], then [test2] (merged into [test1] later on), then [test].
    (CODEBOOK_DOCUMENT_NAME, "this segment", "Trial 1"),
    (CODEBOOK_DOCUMENT_NAME, "this segment", "Trial 1"),
    (CODEBOOK_DOCUMENT_NAME, "this segment", "Trial"),
)


def tutorial_segment_offsets(
    content_by_name: dict[str, str],
) -> list[tuple[str, int, int, str]]:
    """Locate `TUTORIAL_SEGMENTS` as (document name, start, end, code name)."""
    search_from: dict[str, int] = {}
    located = []
    for document_name, passage, code_name in TUTORIAL_SEGMENTS:
        content = content_by_name[document_name]
        start = content.index(f"({passage})", search_from.get(document_name, 0)) + 1
        end = start + len(passage)
        search_from[document_name] = end
        located.append((document_name, start, end, code_name))
    return located


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
    for name in (CODEBOOK_DOCUMENT_NAME, NAVIGATION_DOCUMENT_NAME):
        db.create_document(
            conn, name, tutorial_file_path(name).read_text(encoding="utf-8")
        )
    _seed_tutorial_coding(conn)
    return conn


def _seed_tutorial_coding(conn: sqlite3.Connection) -> None:
    """Add the Tutorial coder's codebook and its coding of the documents.

    The codes are created without colors; `MainWindow.open_tutorial_project`
    assigns them, since the palette lives in the UI.
    """
    code_ids: dict[str, int] = {}
    for name, parent_name in TUTORIAL_CODES:
        parent_id = code_ids[parent_name] if parent_name is not None else None
        code_ids[name] = db.create_code(conn, name, parent_id=parent_id).id
    documents = {doc.name: doc for doc in db.list_documents(conn)}
    content_by_name = {name: doc.content for name, doc in documents.items()}
    for document_name, start, end, code_name in tutorial_segment_offsets(
        content_by_name
    ):
        db.create_segment(
            conn,
            documents[document_name].id,
            code_ids[code_name],
            start,
            end,
            created_by=TUTORIAL_USERNAME,
        )
