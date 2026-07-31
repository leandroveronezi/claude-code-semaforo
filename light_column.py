"""Uma coluna compacta (3 luzes) para uma sessão, embutida no painel único."""
import math
import time

from PyQt6.QtCore import QPoint, QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QPainter, QRadialGradient
from PyQt6.QtWidgets import QWidget

COLUMN_WIDTH = 72  # alinhado com MASCOT_WIDTH em mascot.py
LIGHT_DIAMETER = 16
LIGHT_GAP = 6
TOP_PADDING = 4
STACK_HEIGHT = 3 * LIGHT_DIAMETER + 2 * LIGHT_GAP

LIGHT_COLORS = {
    "error": QColor("#ff453a"),
    "working": QColor("#ffd60a"),
    "idle": QColor("#32d74b"),
}
DIM_COLORS = {
    "error": QColor("#3a1a17"),
    "working": QColor("#39311a"),
    "idle": QColor("#17351f"),
}
BEZEL_COLOR = QColor(0, 0, 0, 90)
ORDER = ("error", "working", "idle")  # topo -> base, como um semáforo real

# barra fina de uso acumulado de tokens, na borda direita da coluna, com a
# contagem desenhada direto no widget (em vez de um QLabel à parte no
# layout) para não sobrar espaço extra quando uma sessão ainda não tem dado
# de uso. Os limiares (valor em tokens -> cor) são configuráveis pelo
# usuário na tela de configurações; os valores abaixo são só o ponto de
# partida (ver DEFAULT_USAGE_THRESHOLDS em config.py, a fonte da verdade).
USAGE_BAR_WIDTH = 4
USAGE_BAR_MARGIN_RIGHT = 6
USAGE_BAR_TRACK_COLOR = QColor(255, 255, 255, 20)
USAGE_TEXT_GAP = 2
USAGE_TEXT_HEIGHT = 11
DEFAULT_USAGE_THRESHOLDS = (
    (100_000, QColor("#32d74b")),
    (150_000, QColor("#ffd60a")),
    (300_000, QColor("#ff453a")),
)

CONTENT_HEIGHT = TOP_PADDING + STACK_HEIGHT + USAGE_TEXT_GAP + USAGE_TEXT_HEIGHT


def _format_tokens(tokens: int) -> str:
    if tokens >= 1000:
        return f"{round(tokens / 1000)}k"
    return str(tokens)


class LightColumn(QWidget):
    def __init__(self, session_id: str, status: str = "idle", parent=None):
        super().__init__(parent)
        self.session_id = session_id
        self.status = status if status in LIGHT_COLORS else "idle"
        self.usage_tokens: int | None = None
        self.usage_enabled = True
        self.thresholds: list[tuple[int, QColor]] = list(DEFAULT_USAGE_THRESHOLDS)

        # deixa os cliques passarem direto para o painel (arrastar funciona em qualquer ponto)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFixedSize(COLUMN_WIDTH, CONTENT_HEIGHT)

        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(40)
        self._pulse_timer.timeout.connect(self.update)
        self._sync_pulse_timer()

    def set_status(self, status: str) -> None:
        if status not in LIGHT_COLORS or status == self.status:
            return
        self.status = status
        self._sync_pulse_timer()
        self.update()

    def set_usage(self, tokens: int | None) -> None:
        if tokens == self.usage_tokens:
            return
        self.usage_tokens = tokens
        self.update()

    def set_show_usage(self, enabled: bool) -> None:
        if enabled == self.usage_enabled:
            return
        self.usage_enabled = enabled
        self.update()

    def set_thresholds(self, thresholds: list[tuple[int, str]]) -> None:
        parsed = [(tokens, QColor(color)) for tokens, color in thresholds]
        parsed.sort(key=lambda t: t[0])
        self.thresholds = parsed or list(DEFAULT_USAGE_THRESHOLDS)
        self.update()

    def _usage_color_and_ratio(self) -> tuple[QColor, float] | None:
        if self.usage_tokens is None or not self.thresholds:
            return None
        max_value = self.thresholds[-1][0]
        ratio = min(self.usage_tokens / max_value, 1.0) if max_value > 0 else 0.0
        color = self.thresholds[-1][1]
        for value, candidate in self.thresholds:
            if self.usage_tokens < value:
                color = candidate
                break
        return color, ratio

    def _sync_pulse_timer(self) -> None:
        if self.status == "working":
            if not self._pulse_timer.isActive():
                self._pulse_timer.start()
        else:
            self._pulse_timer.stop()

    def _pulse_brightness(self) -> float:
        return 0.55 + 0.45 * math.sin(time.monotonic() * 6.0)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        center_x = COLUMN_WIDTH / 2
        top = TOP_PADDING
        for i, name in enumerate(ORDER):
            cy = top + LIGHT_DIAMETER / 2 + i * (LIGHT_DIAMETER + LIGHT_GAP)
            self._draw_light(painter, center_x, cy, name, self.status == name)

        if self.usage_enabled:
            self._draw_usage_bar(painter, top, STACK_HEIGHT)
            self._draw_usage_text(painter, top + STACK_HEIGHT + USAGE_TEXT_GAP)

        painter.end()

    def _draw_usage_bar(self, painter: QPainter, top: float, height: float) -> None:
        x = COLUMN_WIDTH - USAGE_BAR_MARGIN_RIGHT - USAGE_BAR_WIDTH
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(USAGE_BAR_TRACK_COLOR)
        painter.drawRoundedRect(
            int(x), int(top), USAGE_BAR_WIDTH, int(height), USAGE_BAR_WIDTH / 2, USAGE_BAR_WIDTH / 2
        )

        color_and_ratio = self._usage_color_and_ratio()
        if color_and_ratio is None:
            return
        color, ratio = color_and_ratio
        filled = height * ratio
        painter.setBrush(color)
        painter.drawRoundedRect(
            int(x), int(top + height - filled), USAGE_BAR_WIDTH, int(filled),
            USAGE_BAR_WIDTH / 2, USAGE_BAR_WIDTH / 2,
        )

    def _draw_usage_text(self, painter: QPainter, top: float) -> None:
        color_and_ratio = self._usage_color_and_ratio()
        if color_and_ratio is None:
            return
        color, _ratio = color_and_ratio
        font = QFont(painter.font())
        font.setPointSize(6)
        painter.setFont(font)
        painter.setPen(color)
        rect = QRectF(0.0, top, COLUMN_WIDTH, USAGE_TEXT_HEIGHT)
        painter.drawText(
            rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, _format_tokens(self.usage_tokens)
        )

    def _draw_light(self, painter: QPainter, cx: float, cy: float, name: str, active: bool) -> None:
        radius = LIGHT_DIAMETER / 2

        # bisel escuro por trás de toda luz, ativa ou não, para lembrar a lente de um semáforo real
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(BEZEL_COLOR)
        painter.drawEllipse(QPoint(int(cx), int(cy)), int(radius + 2), int(radius + 2))

        if active:
            brightness = self._pulse_brightness() if self.status == "working" else 1.0
            base = LIGHT_COLORS[name]

            glow = QRadialGradient(cx, cy, radius * 2.2)
            inner = QColor(base)
            inner.setAlphaF(0.5 * brightness)
            outer = QColor(base)
            outer.setAlphaF(0.0)
            glow.setColorAt(0.0, inner)
            glow.setColorAt(1.0, outer)
            painter.setBrush(glow)
            painter.drawEllipse(QPoint(int(cx), int(cy)), int(radius * 2.2), int(radius * 2.2))

            color = QColor(base)
            color.setAlphaF(0.65 + 0.35 * brightness)
            painter.setBrush(color)
        else:
            painter.setBrush(DIM_COLORS[name])

        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPoint(int(cx), int(cy)), int(radius), int(radius))

        if active:
            # brilho pequeno no canto, dá volume à esfera
            highlight = QColor(255, 255, 255, int(70 * brightness))
            painter.setBrush(highlight)
            painter.drawEllipse(QPoint(int(cx - radius * 0.35), int(cy - radius * 0.35)), int(radius * 0.3), int(radius * 0.3))
