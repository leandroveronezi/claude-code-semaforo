"""Uma coluna compacta (3 luzes) para uma sessão, embutida no painel único."""
import math
import time

from PyQt6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPen, QRadialGradient
from PyQt6.QtWidgets import QWidget

COLUMN_WIDTH = 72  # alinhado com MASCOT_WIDTH em mascot.py
LIGHT_DIAMETER = 16
LIGHT_GAP = 6
STACK_HEIGHT = 3 * LIGHT_DIAMETER + 2 * LIGHT_GAP

# a luz ativa desenha um brilho (glow) com raio maior que a própria bolinha
# (ver _draw_light); sem essa margem acima/abaixo da pilha, a luz do topo ou
# da base cortaria o brilho na borda do widget quando ativa
LIGHT_GLOW_RADIUS = LIGHT_DIAMETER / 2 * 2.2
TOP_PADDING = math.ceil(LIGHT_GLOW_RADIUS - LIGHT_DIAMETER / 2)
BOTTOM_PADDING = TOP_PADDING

# a coluna é dividida em duas sub-colunas lado a lado (luzes | barra de uso),
# separadas por uma linha fina — proporção ~55/45 como na referência visual
LEFT_COL_WIDTH = 40
RIGHT_COL_WIDTH = COLUMN_WIDTH - LEFT_COL_WIDTH
DIVIDER_COLOR = QColor(255, 255, 255, 30)

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
DOT_RING_COLOR = QColor(255, 255, 255, 40)  # anel da bolinha, mais claro que o preenchimento
ORDER = ("error", "working", "idle")  # topo -> base, como um semáforo real

# barra de uso acumulado de tokens, centralizada na sub-coluna à direita, com a
# contagem desenhada direto no widget (em vez de um QLabel à parte no
# layout) para não sobrar espaço extra quando uma sessão ainda não tem dado
# de uso. Os limiares (valor em tokens -> cor) são configuráveis pelo
# usuário na tela de configurações; os valores abaixo são só o ponto de
# partida (ver DEFAULT_USAGE_THRESHOLDS em config.py, a fonte da verdade).
USAGE_BAR_WIDTH = 8
USAGE_BAR_BORDER_COLOR = QColor(15, 16, 19, 200)
USAGE_BAR_TRACK_COLOR = QColor(70, 72, 79, 210)
USAGE_TEXT_GAP = 2
USAGE_TEXT_BLOCK_HEIGHT = 14  # bloco reservado para o texto, centralizado verticalmente nele
# a barra encolhe para caber junto com o texto na mesma altura total da pilha de luzes,
# assim as duas sub-colunas terminam alinhadas embaixo em vez da barra+texto ficar mais alta
USAGE_BAR_HEIGHT = STACK_HEIGHT - USAGE_TEXT_GAP - USAGE_TEXT_BLOCK_HEIGHT
DEFAULT_USAGE_THRESHOLDS = (
    (100_000, QColor("#32d74b")),
    (150_000, QColor("#ffd60a")),
    (300_000, QColor("#ff453a")),
)

CONTENT_HEIGHT = TOP_PADDING + STACK_HEIGHT + BOTTOM_PADDING

STYLE_SEMAPHORE = "semaphore"  # padrão/original: 3 luzes empilhadas + barra vertical fina ao lado
STYLE_DOT = "dot"  # alternativa compacta: 1 bolinha (cor = status atual) + barra horizontal embaixo

# estilo "dot": bolinha, barra de uso e texto de tokens numa única linha
# (bolinha à esquerda, barra preenchendo o meio, número à direita), em vez da
# divisão em sub-colunas do estilo "semaphore". Coluna bem mais larga que a
# do estilo "semaphore": o painel empilha os cards verticalmente nesse
# estilo (ver SemaphorePanel), então não há mais o mesmo motivo pra manter a
# largura mínima.
DOT_STYLE_WIDTH = 190
DOT_STYLE_BAR_HEIGHT = 8
DOT_STYLE_PADDING = 6  # respiro nas laterais da linha (bolinha à esquerda, texto à direita)
DOT_STYLE_DOT_GAP = 8  # espaço entre a bolinha e a barra
DOT_STYLE_TEXT_GAP = 6  # espaço entre a barra e o texto de tokens
DOT_STYLE_ROW_HEIGHT = max(LIGHT_DIAMETER, DOT_STYLE_BAR_HEIGHT, USAGE_TEXT_BLOCK_HEIGHT)
# padding vertical próprio do estilo dot, menor que TOP_PADDING/BOTTOM_PADDING
# (dimensionado pra pilha de 3 luzes do estilo semaphore): a cauda do glow
# já está com alpha ~0 perto da borda (ver _draw_light), então cortar esses
# últimos pixels de um brilho já quase invisível não fica perceptível.
DOT_STYLE_VPAD = 5
CONTENT_HEIGHT_DOT = DOT_STYLE_VPAD + DOT_STYLE_ROW_HEIGHT + DOT_STYLE_VPAD


def _format_tokens(tokens: int) -> str:
    if tokens >= 1000:
        return f"{round(tokens / 1000)}k"
    return str(tokens)


def _lerp_color(start: QColor, end: QColor, ratio: float) -> QColor:
    ratio = max(0.0, min(ratio, 1.0))
    return QColor(
        round(start.red() + (end.red() - start.red()) * ratio),
        round(start.green() + (end.green() - start.green()) * ratio),
        round(start.blue() + (end.blue() - start.blue()) * ratio),
    )


class LightColumn(QWidget):
    def __init__(self, session_id: str, status: str = "idle", parent=None):
        super().__init__(parent)
        self.session_id = session_id
        self.status = status if status in LIGHT_COLORS else "idle"
        self.usage_tokens: int | None = None
        self.usage_enabled = True
        self.thresholds: list[tuple[int, QColor]] = list(DEFAULT_USAGE_THRESHOLDS)
        self.style = STYLE_SEMAPHORE

        # deixa os cliques passarem direto para o painel (arrastar funciona em qualquer ponto)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFixedSize(*self._content_size())

        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(40)
        self._pulse_timer.timeout.connect(self.update)
        self._sync_pulse_timer()

    def _content_size(self) -> tuple[int, int]:
        if self.style == STYLE_DOT:
            return DOT_STYLE_WIDTH, CONTENT_HEIGHT_DOT
        return COLUMN_WIDTH, CONTENT_HEIGHT

    def set_status(self, status: str) -> None:
        if status not in LIGHT_COLORS or status == self.status:
            return
        self.status = status
        self._sync_pulse_timer()
        self.update()

    def set_style(self, style: str) -> None:
        if style not in (STYLE_SEMAPHORE, STYLE_DOT) or style == self.style:
            return
        self.style = style
        self.setFixedSize(*self._content_size())
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
        # usage_tokens é None até a sessão gerar a primeira resposta (ver
        # _cumulative_usage em hooks/status_hook.py, só populado no Stop) —
        # tratado aqui como 0 pra sessão recém-aberta mostrar "0k" em vez de
        # ficar sem nenhum texto/barra.
        if not self.thresholds:
            return None
        tokens = self.usage_tokens or 0
        max_value = self.thresholds[-1][0]
        ratio = min(tokens / max_value, 1.0) if max_value > 0 else 0.0
        color = self.thresholds[-1][1]
        for value, candidate in self.thresholds:
            if tokens < value:
                color = candidate
                break
        return color, ratio

    def _apply_usage_gradient_stops(self, gradient: QLinearGradient) -> QLinearGradient:
        # cada limiar (value, color) marca onde `color` TERMINA e a próxima cor
        # começa (ex.: (100_000, verde) = verde vale até 100k; a partir dali é
        # a cor do próximo limiar) — mesma regra usada em _usage_color_and_ratio
        # pro número. Por isso a parada de gradiente NAQUELA posição usa a cor
        # do PRÓXIMO limiar, não a dele mesmo: assim o trecho de 0 a 100k já vai
        # transicionando de verde pra amarelo, chegando no amarelo cheio bem em
        # cima dos 100k (33% de um teto de 300k) — coerente com o número, que
        # também vira amarelo exatamente aí.
        max_value = self.thresholds[-1][0]
        if max_value <= 0:
            gradient.setColorAt(0.0, self.thresholds[0][1])
            gradient.setColorAt(1.0, self.thresholds[-1][1])
            return gradient
        gradient.setColorAt(0.0, self.thresholds[0][1])
        last_index = len(self.thresholds) - 1
        for i, (value, color) in enumerate(self.thresholds):
            next_color = self.thresholds[i + 1][1] if i < last_index else color
            gradient.setColorAt(max(0.0, min(value / max_value, 1.0)), next_color)
        return gradient

    def _usage_gradient(self, x: float, top: float, height: float) -> QLinearGradient | None:
        if not self.thresholds:
            return None
        gradient = QLinearGradient(QPointF(x, top + height), QPointF(x, top))  # base=0 -> topo=máximo
        return self._apply_usage_gradient_stops(gradient)

    def _usage_gradient_horizontal(self, x: float, width: float, y: float) -> QLinearGradient | None:
        if not self.thresholds:
            return None
        gradient = QLinearGradient(QPointF(x, y), QPointF(x + width, y))  # início=0 -> fim=máximo
        return self._apply_usage_gradient_stops(gradient)

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

        if self.style == STYLE_DOT:
            self._paint_dot_style(painter)
        else:
            self._paint_semaphore_style(painter)

        painter.end()

    def _paint_semaphore_style(self, painter: QPainter) -> None:
        center_x = LEFT_COL_WIDTH / 2
        top = TOP_PADDING
        for i, name in enumerate(ORDER):
            cy = top + LIGHT_DIAMETER / 2 + i * (LIGHT_DIAMETER + LIGHT_GAP)
            self._draw_light(painter, center_x, cy, name, self.status == name)

        if self.usage_enabled:
            self._draw_divider(painter, top, STACK_HEIGHT)
            self._draw_usage_bar(painter, top, USAGE_BAR_HEIGHT)
            self._draw_usage_text(painter, top + USAGE_BAR_HEIGHT + USAGE_TEXT_GAP, USAGE_TEXT_BLOCK_HEIGHT)

    def _paint_dot_style(self, painter: QPainter) -> None:
        top = DOT_STYLE_VPAD
        cy = top + DOT_STYLE_ROW_HEIGHT / 2
        dot_x = DOT_STYLE_PADDING + LIGHT_DIAMETER / 2
        # sempre "aceso": ao contrário da pilha de 3 luzes, a bolinha única
        # É o status atual, não um indicador que liga/desliga por posição
        self._draw_light(painter, dot_x, cy, self.status, True)

        if self.usage_enabled:
            self._draw_usage_row_horizontal(painter, top, DOT_STYLE_ROW_HEIGHT)

    def _draw_divider(self, painter: QPainter, top: float, height: float) -> None:
        painter.setPen(QPen(DIVIDER_COLOR, 1))
        painter.drawLine(QPointF(LEFT_COL_WIDTH, top), QPointF(LEFT_COL_WIDTH, top + height))

    def _bar_x(self) -> float:
        return LEFT_COL_WIDTH + (RIGHT_COL_WIDTH - USAGE_BAR_WIDTH) / 2

    def _draw_usage_bar(self, painter: QPainter, top: float, height: float) -> None:
        x = self._bar_x()
        painter.setPen(QPen(USAGE_BAR_BORDER_COLOR, 1))
        painter.setBrush(USAGE_BAR_TRACK_COLOR)
        painter.drawRoundedRect(
            int(x), int(top), USAGE_BAR_WIDTH, int(height), USAGE_BAR_WIDTH / 2, USAGE_BAR_WIDTH / 2
        )

        color_and_ratio = self._usage_color_and_ratio()
        if color_and_ratio is None:
            return
        _color, ratio = color_and_ratio
        gradient = self._usage_gradient(x, top, height)
        if gradient is None:
            return
        filled = height * ratio
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(gradient)
        painter.drawRoundedRect(
            int(x), int(top + height - filled), USAGE_BAR_WIDTH, int(filled),
            USAGE_BAR_WIDTH / 2, USAGE_BAR_WIDTH / 2,
        )

    def _draw_usage_text(self, painter: QPainter, top: float, height: float) -> None:
        color_and_ratio = self._usage_color_and_ratio()
        if color_and_ratio is None:
            return
        color, _ratio = color_and_ratio
        font = QFont(painter.font())
        font.setPointSize(6)
        painter.setFont(font)
        painter.setPen(color)
        # centralizado (horizontal e vertical) no bloco reservado abaixo da barra,
        # em vez de colado no topo logo após a barra
        rect = QRectF(LEFT_COL_WIDTH, top, RIGHT_COL_WIDTH, height)
        painter.drawText(
            rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            _format_tokens(self.usage_tokens or 0),
        )

    def _draw_usage_row_horizontal(self, painter: QPainter, top: float, height: float) -> None:
        bar_height = DOT_STYLE_BAR_HEIGHT
        bar_top = top + (height - bar_height) / 2
        bar_x = DOT_STYLE_PADDING + LIGHT_DIAMETER + DOT_STYLE_DOT_GAP

        font = QFont(painter.font())
        font.setPointSize(6)
        text = _format_tokens(self.usage_tokens or 0)
        # largura da barra calculada a partir do texto REAL (não de uma caixa
        # de largura fixa pro maior valor possível): assim o vão barra->texto
        # e texto->borda ficam sempre iguais, em vez de sobrar espaço vazio
        # de um lado ou do outro quando o número tem poucos dígitos ("58k").
        text_width = QFontMetrics(font).horizontalAdvance(text)
        bar_width = self.width() - bar_x - DOT_STYLE_TEXT_GAP - text_width - DOT_STYLE_PADDING

        painter.setPen(QPen(USAGE_BAR_BORDER_COLOR, 1))
        painter.setBrush(USAGE_BAR_TRACK_COLOR)
        painter.drawRoundedRect(
            QRectF(bar_x, bar_top, bar_width, bar_height), bar_height / 2, bar_height / 2
        )

        color_and_ratio = self._usage_color_and_ratio()
        if color_and_ratio is None:
            return
        color, ratio = color_and_ratio
        gradient = self._usage_gradient_horizontal(bar_x, bar_width, bar_top + bar_height / 2)
        if gradient is not None:
            filled = bar_width * ratio
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(gradient)
            painter.drawRoundedRect(
                QRectF(bar_x, bar_top, filled, bar_height), bar_height / 2, bar_height / 2
            )

        painter.setFont(font)
        painter.setPen(color)
        text_x = bar_x + bar_width + DOT_STYLE_TEXT_GAP
        text_rect = QRectF(text_x, top, text_width, height)
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)

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

        painter.setPen(QPen(DOT_RING_COLOR, 1) if not active else Qt.PenStyle.NoPen)
        painter.drawEllipse(QPoint(int(cx), int(cy)), int(radius), int(radius))
        painter.setPen(Qt.PenStyle.NoPen)

        if active:
            # brilho pequeno no canto, dá volume à esfera
            highlight = QColor(255, 255, 255, int(70 * brightness))
            painter.setBrush(highlight)
            painter.drawEllipse(QPoint(int(cx - radius * 0.35), int(cy - radius * 0.35)), int(radius * 0.3), int(radius * 0.3))
