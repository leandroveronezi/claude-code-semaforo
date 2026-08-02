"""Caixa deitada com a cota da conta (Sessão 5h / Semana 7d), exibida
abaixo do mascote — mesmo dado raspado da tela `/usage` do CLI por
account_usage.py. Mesmo padrão do SpeechBubble (speech_bubble.py):
has_content/content_size() ficam em (0, 0) enquanto não há dado nenhum, então
ela some completamente do layout (mascot_overlay._relayout) até a primeira
consulta responder."""
from PyQt6.QtCore import QPointF, QRectF, QSize, Qt
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPainterPath
from PyQt6.QtWidgets import QWidget

from config import DEFAULT_PANEL_OPACITY_PERCENT, MIN_PANEL_OPACITY_PERCENT

MIN_WIDTH = 168
PADDING = 10
LABEL_PCT_GAP = 12  # espaço mínimo entre "rótulo" e "pct%" na mesma linha
ROW_GAP = 8
BAR_HEIGHT = 5
BAR_GAP = 3  # entre o texto "rótulo / pct" e a barra
HINT_GAP = 2  # entre a barra e o texto de "reseta ..."
CORNER_RADIUS = 10

BACKGROUND_RGB = (24, 24, 28)
BORDER_COLOR = QColor(255, 255, 255, 30)
TRACK_COLOR = QColor(255, 255, 255, 25)
# gradiente estilo semáforo (verde -> amarelo -> vermelho) ao longo da barra
# inteira; o preenchimento revela progressivamente a cor correspondente à
# proximidade do limite, mesma linguagem visual do 🔴🟡🟢 do painel principal.
BAR_COLOR_LOW = QColor("#30d158")
BAR_COLOR_MID = QColor("#ffd60a")
BAR_COLOR_HIGH = QColor("#ff453a")
TEXT_COLOR = QColor(230, 230, 234)
HINT_COLOR = QColor(138, 138, 146)

FONT_POINT_SIZE = 7.5
HINT_POINT_SIZE = 6.5

Row = tuple[str, int, str]  # (rótulo, porcentagem, texto de quando reseta)


class AccountUsageBadge(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        # igual ao balão: cliques passam direto pro mascote/janela por trás
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        self._font = QFont(self.font())
        self._font.setPointSizeF(FONT_POINT_SIZE)
        self._hint_font = QFont(self.font())
        self._hint_font.setPointSizeF(HINT_POINT_SIZE)

        self._rows: list[Row] = []
        self._opacity = DEFAULT_PANEL_OPACITY_PERCENT / 100.0
        self.setFixedSize(0, 0)

    @property
    def has_content(self) -> bool:
        return bool(self._rows)

    def set_opacity(self, percent: int) -> None:
        opacity = max(MIN_PANEL_OPACITY_PERCENT, min(100, percent)) / 100.0
        if opacity == self._opacity:
            return
        self._opacity = opacity
        self.update()

    def content_size(self) -> QSize:
        if not self._rows:
            return QSize(0, 0)
        row_h = self._row_height()
        height = len(self._rows) * row_h + (len(self._rows) - 1) * ROW_GAP + 2 * PADDING
        return QSize(self._content_width(), round(height))

    def _content_width(self) -> int:
        # largura cresce pra caber o texto de reset (ex: "reseta Aug 4,
        # 11:59am (America/Sao_Paulo)"), que costuma ser mais largo que o
        # MIN_WIDTH base — nunca elide em vez de mostrar a data completa.
        label_metrics = QFontMetrics(self._font)
        hint_metrics = QFontMetrics(self._hint_font)
        needed = MIN_WIDTH
        for label, pct, reset_text in self._rows:
            row_width = (
                label_metrics.horizontalAdvance(label)
                + LABEL_PCT_GAP
                + label_metrics.horizontalAdvance(f"{pct}%")
                + 2 * PADDING
            )
            needed = max(needed, row_width)
            if reset_text:
                hint_width = hint_metrics.horizontalAdvance(f"reseta {reset_text}") + 2 * PADDING
                needed = max(needed, hint_width)
        return round(needed)

    def _row_height(self) -> float:
        return (
            QFontMetrics(self._font).height()
            + BAR_GAP + BAR_HEIGHT + HINT_GAP
            + QFontMetrics(self._hint_font).height()
        )

    def set_usage(self, data: "dict | None") -> None:
        rows: list[Row] = []
        if data:
            session_pct = data.get("session_pct")
            if session_pct is not None:
                rows.append(("Sessão (5h)", session_pct, data.get("session_resets") or ""))
            week_pct = data.get("week_pct")
            if week_pct is not None:
                rows.append(("Semana (7d)", week_pct, data.get("week_resets") or ""))
        if rows == self._rows:
            return
        self._rows = rows
        self.setFixedSize(self.content_size())
        self.update()

    def paintEvent(self, _event) -> None:
        if not self._rows:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, self.width(), self.height()), CORNER_RADIUS, CORNER_RADIUS)
        border = QColor(BORDER_COLOR)
        border.setAlpha(round(BORDER_COLOR.alpha() * self._opacity))
        background = QColor(*BACKGROUND_RGB, round(255 * self._opacity))
        painter.setPen(border)
        painter.setBrush(background)
        painter.drawPath(path)

        label_metrics = QFontMetrics(self._font)
        hint_metrics = QFontMetrics(self._hint_font)
        bar_width = self.width() - 2 * PADDING
        row_h = self._row_height()

        y = float(PADDING)
        for label, pct, reset_text in self._rows:
            painter.setFont(self._font)
            painter.setPen(TEXT_COLOR)
            text_y = y + label_metrics.ascent()
            painter.drawText(PADDING, int(text_y), label)
            pct_text = f"{pct}%"
            pct_x = self.width() - PADDING - label_metrics.horizontalAdvance(pct_text)
            painter.drawText(int(pct_x), int(text_y), pct_text)

            bar_y = y + label_metrics.height() + BAR_GAP
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(TRACK_COLOR)
            painter.drawRoundedRect(PADDING, int(bar_y), int(bar_width), BAR_HEIGHT, BAR_HEIGHT / 2, BAR_HEIGHT / 2)
            filled = bar_width * max(0, min(pct, 100)) / 100
            if filled > 0:
                gradient = QLinearGradient(QPointF(PADDING, 0), QPointF(PADDING + bar_width, 0))
                gradient.setColorAt(0.0, BAR_COLOR_LOW)
                gradient.setColorAt(0.6, BAR_COLOR_MID)
                gradient.setColorAt(1.0, BAR_COLOR_HIGH)
                painter.setBrush(gradient)
                painter.drawRoundedRect(PADDING, int(bar_y), round(filled), BAR_HEIGHT, BAR_HEIGHT / 2, BAR_HEIGHT / 2)

            if reset_text:
                painter.setFont(self._hint_font)
                painter.setPen(HINT_COLOR)
                hint_y = bar_y + BAR_HEIGHT + HINT_GAP + hint_metrics.ascent()
                elided = hint_metrics.elidedText(f"reseta {reset_text}", Qt.TextElideMode.ElideRight, int(bar_width))
                painter.drawText(PADDING, int(hint_y), elided)

            y += row_h + ROW_GAP

        painter.end()
