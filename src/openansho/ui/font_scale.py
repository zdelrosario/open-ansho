"""Application-wide font scaling.

The user-facing setting is a *percentage* of the platform's own default UI
font, so 100% always means "whatever this machine normally uses" rather than
a hardcoded point size that would look wrong on some displays.

Two things have to happen for a scale to take effect everywhere:

* `apply_font_scale` sets `QApplication`'s font, which is what any widget
  created from then on (dialogs, menus, message boxes) starts out with; and
* `font_scale_style` returns a QSS fragment that `MainWindow` appends to its
  theme stylesheet. This one is not redundant: setting a stylesheet on a
  widget makes Qt give every widget it polishes an explicit font, which then
  stops following `QApplication`'s — so already-built panes only resize when
  the size comes through the stylesheet as well.
"""

from __future__ import annotations

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

DEFAULT_FONT_SCALE_PERCENT = 100
MIN_FONT_SCALE_PERCENT = 50
MAX_FONT_SCALE_PERCENT = 400
FONT_SCALE_STEP_PERCENT = 25

# The unscaled application font, captured the first time a scale is applied
# (i.e. before we've overwritten QApplication's font with a scaled one).
# Percentages are always measured against this, so repeated increases and
# decreases can't compound rounding into a drifting base size.
_base_font: QFont | None = None


def base_font() -> QFont:
    """The application font as it was before any scaling was applied."""
    global _base_font
    if _base_font is None:
        _base_font = QFont(QApplication.instance().font())
    return QFont(_base_font)


def clamp_font_scale(percent: int) -> int:
    return max(MIN_FONT_SCALE_PERCENT, min(MAX_FONT_SCALE_PERCENT, int(percent)))


def scaled_font(percent: int) -> QFont:
    """The base font resized to `percent` of its original size."""
    font = base_font()
    point_size = font.pointSizeF()
    if point_size > 0:
        # Qt's stylesheet parser rejects fractional point sizes, and the two
        # sizes must agree, so round here rather than in font_scale_style.
        font.setPointSize(max(1, round(point_size * percent / 100)))
    else:
        # Fonts defined in pixels rather than points report pointSizeF() == -1.
        font.setPixelSize(max(1, round(font.pixelSize() * percent / 100)))
    return font


def font_scale_style(percent: int) -> str:
    """QSS sizing every widget under it to `percent` of the default font."""
    font = scaled_font(percent)
    size = (
        f"{font.pointSize()}pt" if font.pointSize() > 0 else f"{font.pixelSize()}px"
    )
    return "QWidget { font-size: %s; }\n" % size


def apply_font_scale(percent: int) -> None:
    """Make `percent` the default font size for newly created widgets."""
    # Computing the scaled font first matters: it captures the base font while
    # QApplication still carries it, before setFont replaces it with a scaled one.
    font = scaled_font(percent)
    QApplication.instance().setFont(font)
