"""Painting shared by the two places a coded thing is drawn.

The text pane (`vim_viewer.VimTextViewer`) and the PDF page pane
(`pdf_page_view.PdfPageView`) both have to show a span carrying more than one
code at once, and they show it the same way so the two panes read alike.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPolygonF


def paint_diagonal_stripes(
    painter: QPainter, rect: QRectF, colors: tuple[QColor, ...], stripe_width: float
) -> None:
    """Fill `rect` with diagonal (bottom-left to top-right) stripes cycling
    through `colors`, so something carrying several codes shows every color at
    once instead of only the last one painted over the rest."""
    stripe_width = max(stripe_width, 1)
    shear = rect.height()

    painter.save()
    painter.setClipRect(rect, Qt.IntersectClip)
    painter.setPen(Qt.NoPen)
    x = rect.left() - shear
    index = 0
    while x < rect.right() + shear:
        painter.setBrush(colors[index % len(colors)])
        painter.drawPolygon(
            QPolygonF(
                [
                    QPointF(x, rect.bottom()),
                    QPointF(x + shear, rect.top()),
                    QPointF(x + shear + stripe_width, rect.top()),
                    QPointF(x + stripe_width, rect.bottom()),
                ]
            )
        )
        x += stripe_width
        index += 1
    painter.restore()
