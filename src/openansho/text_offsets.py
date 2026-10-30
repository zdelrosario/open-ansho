"""Reading `documents.content` at offsets measured by Qt.

Qt counts text in UTF-16 code units, so a character outside the Basic
Multilingual Plane (an emoji, or a math-italic 𝑥 out of a PDF) takes two
cursor positions in a QTextDocument but one index in a Python `str`.
Segment and region offsets are Qt positions, since they come from the
viewer's text cursor, so Python code that slices the stored text with
them has to convert first or it drifts by one character per such
character earlier in the document.
"""

import re

_ASTRAL = re.compile("[\U00010000-\U0010FFFF]")


def qt_width(character: str) -> int:
    """How many Qt positions `character` occupies."""
    return 2 if character > "￿" else 1


def to_qt_position(text: str, index: int) -> int:
    """The Qt position of Python index `index` in `text`."""
    return index + sum(1 for _ in _ASTRAL.finditer(text, 0, index))


def from_qt_position(text: str, position: int) -> int:
    """The Python index of Qt position `position` in `text`.

    A position between the two halves of a surrogate pair rounds down to
    the character it splits.
    """
    index = position
    for count, match in enumerate(_ASTRAL.finditer(text, 0, position)):
        if match.start() + count >= position:
            break
        index -= 1
    return index


def qt_slice(text: str, start: int, end: int) -> str:
    """`text` between Qt positions `start` and `end`."""
    return text[from_qt_position(text, start) : from_qt_position(text, end)]
