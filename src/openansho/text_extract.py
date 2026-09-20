"""Turn an on-disk document into the plain text OpenAnsho codes against.

Like `db.py` and `reporting.py`, this module has no Qt imports: the UI hands it
a path and gets back a string (or a `DocumentReadError` carrying a message fit
for a dialog).

The `.docx` reader is hand-rolled on top of `zipfile`/`xml.etree` rather than
`python-docx` so the packaged app keeps its single third-party dependency.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

W_NAMESPACE = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
DOCX_BODY_PART = "word/document.xml"


class DocumentReadError(Exception):
    """A document couldn't be read; the message is shown to the user as-is."""


def read_document_text(path: Path) -> str:
    """Read `path` as plain text, dispatching on its extension."""
    suffix = path.suffix.lower()
    if suffix == ".docx":
        return read_docx_text(path)
    if suffix == ".doc":
        raise DocumentReadError(
            f"{path.name} is a legacy Word document. Open it in Word and save it "
            "as .docx (or plain text), then import that."
        )
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise DocumentReadError(f"Could not read {path.name} as UTF-8 text.") from None
    except OSError as exc:
        raise DocumentReadError(f"Could not read {path.name}: {exc}") from None


def read_docx_text(path: Path) -> str:
    """Extract the body text of a `.docx` file, one line per paragraph.

    Paragraphs are visited in document order, including those nested inside
    tables (each table cell's paragraphs become their own lines).
    """
    try:
        with zipfile.ZipFile(path) as archive:
            try:
                body_xml = archive.read(DOCX_BODY_PART)
            except KeyError:
                raise DocumentReadError(
                    f"{path.name} is not a valid Word document "
                    f"(it has no {DOCX_BODY_PART})."
                ) from None
    except zipfile.BadZipFile:
        raise DocumentReadError(
            f"{path.name} is not a valid Word document (it is not a .docx archive)."
        ) from None
    except OSError as exc:
        raise DocumentReadError(f"Could not read {path.name}: {exc}") from None

    try:
        root = ET.fromstring(body_xml)
    except ET.ParseError as exc:
        raise DocumentReadError(f"Could not parse {path.name}: {exc}") from None

    body = root.find(_w("body"))
    if body is None:
        body = root
    paragraphs = [_paragraph_text(p) for p in body.iter(_w("p"))]
    return "\n".join(paragraphs)


def _w(tag: str) -> str:
    return f"{{{W_NAMESPACE}}}{tag}"


def _paragraph_text(paragraph: ET.Element) -> str:
    """Flatten one `w:p` into a line of text.

    Only `w:t` runs contribute characters, which conveniently skips field
    instructions (`w:instrText`) and tracked deletions (`w:delText`); tabs and
    in-paragraph breaks are preserved as whitespace.
    """
    pieces: list[str] = []
    for node in paragraph.iter():
        tag = node.tag
        if tag == _w("t"):
            pieces.append(node.text or "")
        elif tag == _w("tab"):
            pieces.append("\t")
        elif tag in (_w("br"), _w("cr")):
            pieces.append("\n")
    return "".join(pieces)
