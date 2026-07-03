"""Balão de fala que aparece acima do mascote com um preview da última resposta."""
from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QFontMetrics, QPainter, QPainterPath
from PyQt6.QtWidgets import QWidget

BUBBLE_WIDTH = 150
PADDING = 8
TAIL_HEIGHT = 7
TAIL_WIDTH = 12
CORNER_RADIUS = 10
PREVIEW_LIMIT = 150
FONT_POINT_SIZE = 7.5
LINE_SPACING = 3

BACKGROUND_COLOR = QColor(242, 242, 238, 245)
BORDER_COLOR = QColor(0, 0, 0, 40)
TEXT_COLOR = QColor(30, 30, 32)


def _truncate(text: str, limit: int = PREVIEW_LIMIT) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    cut = collapsed[:limit]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut + "…"


class SpeechBubble(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFixedWidth(BUBBLE_WIDTH)

        font = self.font()
        font.setPointSizeF(FONT_POINT_SIZE)
        self.setFont(font)

        self._preview = ""
        self._lines: list[str] = []
        self.setFixedHeight(0)

    def set_message(self, text: str | None) -> None:
        if not text:
            if self._preview:
                self._preview = ""
                self._lines = []
                self.setToolTip("")
                self.setFixedHeight(0)
                self.update()
            return

        preview = _truncate(text)
        if preview == self._preview:
            return

        self._preview = preview
        self.setToolTip(text)
        self._lines = self._wrap_lines(preview)

        metrics = QFontMetrics(self.font())
        text_height = len(self._lines) * (metrics.height() + LINE_SPACING) - LINE_SPACING
        self.setFixedHeight(int(text_height + 2 * PADDING + TAIL_HEIGHT))
        self.update()

    def _wrap_lines(self, text: str) -> list[str]:
        metrics = QFontMetrics(self.font())
        max_width = BUBBLE_WIDTH - 2 * PADDING
        lines: list[str] = []
        current = ""
        for word in text.split(" "):
            candidate = f"{current} {word}".strip()
            if metrics.horizontalAdvance(candidate) <= max_width or not current:
                current = candidate
            else:
                lines.append(current)
                current = word
        if current:
            lines.append(current)
        return lines

    def paintEvent(self, _event) -> None:
        if not self._lines:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        body_rect = QRectF(0, 0, BUBBLE_WIDTH, self.height() - TAIL_HEIGHT)

        path = QPainterPath()
        path.addRoundedRect(body_rect, CORNER_RADIUS, CORNER_RADIUS)
        tail_cx = BUBBLE_WIDTH / 2
        path.moveTo(tail_cx - TAIL_WIDTH / 2, body_rect.bottom() - 1)
        path.lineTo(tail_cx, body_rect.bottom() + TAIL_HEIGHT)
        path.lineTo(tail_cx + TAIL_WIDTH / 2, body_rect.bottom() - 1)
        path.closeSubpath()

        painter.setPen(BORDER_COLOR)
        painter.setBrush(BACKGROUND_COLOR)
        painter.drawPath(path)

        painter.setPen(TEXT_COLOR)
        metrics = QFontMetrics(self.font())
        y = PADDING + metrics.ascent()
        for line in self._lines:
            painter.drawText(int(PADDING), int(y), line)
            y += metrics.height() + LINE_SPACING

        painter.end()
