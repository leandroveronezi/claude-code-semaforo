"""Balão de fala que aparece ao lado do mascote com um preview da última
resposta. O rabinho (tail) pode apontar pra baixo, esquerda ou direita —
quem decide o lado é o posicionamento inteligente em mascot_overlay.py,
conforme o mascote esteja perto de qual borda da tela."""
from PyQt6.QtCore import QRectF, QSize, Qt
from PyQt6.QtGui import QColor, QFontMetrics, QPainter, QPainterPath
from PyQt6.QtWidgets import QWidget

BUBBLE_WIDTH = 150
PADDING = 8
TAIL_HEIGHT = 7  # o quanto o rabinho protrai pra fora do corpo, em qualquer lado
TAIL_WIDTH = 12  # largura da base do rabinho, na aresta em que ele nasce
CORNER_RADIUS = 10
DEFAULT_PREVIEW_LIMIT = 150  # valor de fábrica; configurável via Config.mascot_message_limit
FONT_POINT_SIZE = 7.5
LINE_SPACING = 3

BACKGROUND_COLOR = QColor(242, 242, 238, 245)
BORDER_COLOR = QColor(0, 0, 0, 40)
TEXT_COLOR = QColor(30, 30, 32)


def _truncate(text: str, limit: int) -> str:
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

        font = self.font()
        font.setPointSizeF(FONT_POINT_SIZE)
        self.setFont(font)

        self._preview = ""
        self._lines: list[str] = []
        self._tail_side = "bottom"  # "bottom" | "left" | "right"
        self._char_limit = DEFAULT_PREVIEW_LIMIT
        self.setFixedSize(0, 0)

    def set_char_limit(self, limit: int) -> None:
        self._char_limit = limit

    @property
    def has_content(self) -> bool:
        return bool(self._lines)

    def content_size(self) -> QSize:
        """Tamanho do "corpo" do balão (sem o rabinho), independente do lado
        do rabinho — usado por quem decide o layout antes de aplicá-lo."""
        if not self._lines:
            return QSize(0, 0)
        metrics = QFontMetrics(self.font())
        text_height = len(self._lines) * (metrics.height() + LINE_SPACING) - LINE_SPACING
        return QSize(BUBBLE_WIDTH, int(text_height + 2 * PADDING))

    def set_message(self, text: str | None) -> None:
        if not text:
            if self._preview:
                self._preview = ""
                self._lines = []
                self.setToolTip("")
                self._apply_size()
            return

        preview = _truncate(text, self._char_limit)
        if preview == self._preview:
            return

        self._preview = preview
        self.setToolTip(text)
        self._lines = self._wrap_lines(preview)
        self._apply_size()

    def set_tail_side(self, side: str) -> None:
        side = side if side in ("bottom", "left", "right") else "bottom"
        if side != self._tail_side:
            self._tail_side = side
            self._apply_size()

    def _apply_size(self) -> None:
        body = self.content_size()
        if body.isEmpty():
            self.setFixedSize(0, 0)
        elif self._tail_side == "bottom":
            self.setFixedSize(body.width(), body.height() + TAIL_HEIGHT)
        else:
            self.setFixedSize(body.width() + TAIL_HEIGHT, body.height())
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

        if self._tail_side == "bottom":
            body_rect = QRectF(0, 0, BUBBLE_WIDTH, self.height() - TAIL_HEIGHT)
        elif self._tail_side == "left":
            body_rect = QRectF(TAIL_HEIGHT, 0, BUBBLE_WIDTH, self.height())
        else:  # right
            body_rect = QRectF(0, 0, BUBBLE_WIDTH, self.height())

        path = QPainterPath()
        path.addRoundedRect(body_rect, CORNER_RADIUS, CORNER_RADIUS)

        if self._tail_side == "bottom":
            tail_cx = body_rect.center().x()
            path.moveTo(tail_cx - TAIL_WIDTH / 2, body_rect.bottom() - 1)
            path.lineTo(tail_cx, body_rect.bottom() + TAIL_HEIGHT)
            path.lineTo(tail_cx + TAIL_WIDTH / 2, body_rect.bottom() - 1)
            path.closeSubpath()
        elif self._tail_side == "left":
            tail_cy = body_rect.center().y()
            path.moveTo(body_rect.left() + 1, tail_cy - TAIL_WIDTH / 2)
            path.lineTo(body_rect.left() - TAIL_HEIGHT, tail_cy)
            path.lineTo(body_rect.left() + 1, tail_cy + TAIL_WIDTH / 2)
            path.closeSubpath()
        else:  # right
            tail_cy = body_rect.center().y()
            path.moveTo(body_rect.right() - 1, tail_cy - TAIL_WIDTH / 2)
            path.lineTo(body_rect.right() + TAIL_HEIGHT, tail_cy)
            path.lineTo(body_rect.right() - 1, tail_cy + TAIL_WIDTH / 2)
            path.closeSubpath()

        painter.setPen(BORDER_COLOR)
        painter.setBrush(BACKGROUND_COLOR)
        painter.drawPath(path)

        painter.setPen(TEXT_COLOR)
        metrics = QFontMetrics(self.font())
        x0 = body_rect.left() + PADDING
        y = body_rect.top() + PADDING + metrics.ascent()
        for line in self._lines:
            painter.drawText(int(x0), int(y), line)
            y += metrics.height() + LINE_SPACING

        painter.end()
