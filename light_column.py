"""Uma coluna compacta (rótulo + 3 luzes) para uma sessão, embutida no painel único."""
import math
import time

from PyQt6.QtCore import QPoint, QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter, QRadialGradient
from PyQt6.QtWidgets import QWidget

COLUMN_WIDTH = 72  # alinhado com MASCOT_WIDTH em mascot.py
LIGHT_DIAMETER = 16
LIGHT_GAP = 6
LABEL_HEIGHT = 15

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

CONTENT_HEIGHT = LABEL_HEIGHT + 3 * LIGHT_DIAMETER + 2 * LIGHT_GAP + 6


class LightColumn(QWidget):
    def __init__(self, session_id: str, label: str, status: str = "idle", parent=None):
        super().__init__(parent)
        self.session_id = session_id
        self.label = label
        self.status = status if status in LIGHT_COLORS else "idle"

        # deixa os cliques passarem direto para o painel (arrastar funciona em qualquer ponto)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFixedSize(COLUMN_WIDTH, CONTENT_HEIGHT)

        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(40)
        self._pulse_timer.timeout.connect(self.update)
        self._sync_pulse_timer()

    def set_label(self, label: str) -> None:
        if label != self.label:
            self.label = label
            self.setToolTip(label)
            self.update()

    def set_status(self, status: str) -> None:
        if status not in LIGHT_COLORS or status == self.status:
            return
        self.status = status
        self._sync_pulse_timer()
        self.update()

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

        active_color = LIGHT_COLORS[self.status]
        painter.setPen(QColor(active_color.red(), active_color.green(), active_color.blue(), 235))
        font = painter.font()
        font.setPointSize(6)
        font.setWeight(QFont.Weight.DemiBold)
        font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 102)
        painter.setFont(font)
        metrics = QFontMetrics(font)
        elided = metrics.elidedText(self.label, Qt.TextElideMode.ElideRight, COLUMN_WIDTH)
        painter.drawText(
            QRectF(0, 0, COLUMN_WIDTH, LABEL_HEIGHT),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            elided,
        )

        center_x = COLUMN_WIDTH / 2
        top = LABEL_HEIGHT + 5
        for i, name in enumerate(ORDER):
            cy = top + LIGHT_DIAMETER / 2 + i * (LIGHT_DIAMETER + LIGHT_GAP)
            self._draw_light(painter, center_x, cy, name, self.status == name)

        painter.end()

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
