"""Painel único, flutuante e arrastável que agrupa título + semáforo
compacto por sessão, lado a lado (em vez de abrir uma janela separada para
cada uma). O mascote é único e vive à parte, em mascot_overlay.py."""
from PyQt6.QtCore import QEasingCurve, QEvent, QPoint, QSize, Qt, QTimer, QVariantAnimation, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QFontMetrics,
    QGuiApplication,
    QLinearGradient,
    QPainter,
    QPalette,
    QPen,
)
from PyQt6.QtWidgets import QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from config import DEFAULT_PANEL_OPACITY_PERCENT, MIN_PANEL_OPACITY_PERCENT
from light_column import (
    COLUMN_WIDTH,
    CONTENT_HEIGHT,
    DOT_STYLE_WIDTH,
    LIGHT_COLORS,
    STYLE_DOT,
    STYLE_SEMAPHORE,
    LightColumn,
)

PADDING = 9
COLUMN_GAP = 8  # espaço entre luzes lado a lado, no estilo semaphore
DOT_STYLE_CARD_GAP = 4  # espaço entre cards empilhados, no estilo dot (lista vertical)
CARD_PADDING = 10  # respiro dentro do card de cada sessão, ao redor de título+semáforo
# espaço entre título e luzes: CARD_PADDING abaixo do título (simétrico ao
# respiro acima, centralizando o título na faixa de cabeçalho) + um respiro
# menor entre a linha divisória e o semáforo
COLUMN_SPACING = CARD_PADDING + 4
CARD_CORNER_RADIUS = 12
CARD_WIDTH = COLUMN_WIDTH + 2 * CARD_PADDING
DOT_CARD_WIDTH = DOT_STYLE_WIDTH + 2 * CARD_PADDING
CARD_BG_RGB = (37, 38, 43)
CARD_BORDER_COLOR = QColor(255, 255, 255, 42)
CARD_DIVIDER_COLOR = QColor(255, 255, 255, 32)  # linha entre o título e o semáforo, dentro do card
RESIZE_ANIMATION_MS = 160
PLACEHOLDER_WIDTH = 140
SHADOW_MARGIN = 16  # espaço em volta do painel só para a sombra suave renderizar
CORNER_RADIUS = 16
TOOLTIP_OFFSET = QPoint(14, 18)  # deslocamento do cursor, como o tooltip nativo
RAISE_INTERVAL_MS = 300  # reforço periódico de empilhamento (ver _AlwaysOnTopTooltip)


def _with_alpha_factor(color: QColor, factor: float) -> QColor:
    """Cópia de `color` com o canal alpha escalado por `factor` (0-1), usada
    para aplicar a opacidade configurável do painel (ver Config.panel_opacity)
    a bordas/divisores sem alterar as constantes de cor base."""
    scaled = QColor(color)
    scaled.setAlpha(round(color.alpha() * factor))
    return scaled


def _bg_color(rgb: tuple[int, int, int], opacity: float) -> QColor:
    """Cor de fundo (fill) pra um dado `opacity` (0-1) tratado como fração
    real do canal alpha (255 = totalmente sólido) — não uma fração das
    constantes de design originais, que já eram elas mesmas ~92-94%
    translúcidas (ver DEFAULT_PANEL_OPACITY_PERCENT em config.py)."""
    r, g, b = rgb
    return QColor(r, g, b, round(255 * opacity))


class _AlwaysOnTopTooltip(QLabel):
    """Substitui o QToolTip nativo: janelas com WindowStaysOnTopHint não têm
    ordem garantida *entre si* em vários WMs/compositores Linux — o painel, o
    mascote (mascot_overlay.py) e este popup competem pelo topo, e qualquer
    um deles pode acabar atrás dos outros dependendo de qual foi ativado por
    último. Por isso nos reforçamos no topo com raise_() periódico enquanto
    visíveis, em vez de confiar numa única chamada de show()."""

    _instance: "_AlwaysOnTopTooltip | None" = None

    def __init__(self):
        super().__init__(
            None,
            Qt.WindowType.ToolTip
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setWordWrap(True)
        self.setMargin(6)
        self.setStyleSheet(
            "background-color: #2b2b2f; color: #f0f0f0; border: 1px solid rgba(255,255,255,40);"
            " border-radius: 5px; font-size: 11px;"
        )
        self._raise_timer = QTimer(self)
        self._raise_timer.setInterval(RAISE_INTERVAL_MS)
        self._raise_timer.timeout.connect(self.raise_)

    @classmethod
    def instance(cls) -> "_AlwaysOnTopTooltip":
        if cls._instance is None:
            cls._instance = cls()
        else:
            try:
                cls._instance.isVisible()  # força um toque no wrapper: RuntimeError se o C++ já foi destruído
            except RuntimeError:
                cls._instance = cls()
        return cls._instance

    @classmethod
    def show_text(cls, text: str) -> None:
        popup = cls.instance()
        popup.setText(text)
        popup.adjustSize()
        popup.move(QCursor.pos() + TOOLTIP_OFFSET)
        popup.show()
        popup.raise_()
        popup._raise_timer.start()

    @classmethod
    def hide_tooltip(cls) -> None:
        if cls._instance is None:
            return
        try:
            cls._instance._raise_timer.stop()
            cls._instance.hide()
        except RuntimeError:
            cls._instance = None


class _TitleLabel(QLabel):
    """Nome da sessão, elidido, com a cor acompanhando o status atual."""

    def __init__(self, width: int, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.setFixedWidth(width)
        self._raw_text = ""
        font = self.font()
        font.setPointSize(6)
        font.setWeight(QFont.Weight.DemiBold)
        font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 102)
        self.setFont(font)

    def set_width(self, width: int) -> None:
        if width == self.width():
            return
        self.setFixedWidth(width)
        self.set_text(self._raw_text)  # reelide pro novo tamanho

    def set_text(self, text: str) -> None:
        self._raw_text = text
        metrics = QFontMetrics(self.font())
        self.setText(metrics.elidedText(text, Qt.TextElideMode.ElideRight, self.width()))

    def set_status_color(self, status: str) -> None:
        # usa QPalette em vez de setStyleSheet: qualquer stylesheet aplicado
        # a um QLabel ativa o motor de estilos do Qt (QStyleSheetStyle), que
        # passa a pintar um retângulo de fundo opaco do tamanho do label —
        # aparecendo como um "quadrado" mais escuro sobre o card
        # semi-transparente desenhado em _SessionColumn.paintEvent.
        color = LIGHT_COLORS.get(status, LIGHT_COLORS["idle"])
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.WindowText, color)
        self.setPalette(palette)


class _SessionColumn(QWidget):
    """Empilha título e semáforo de uma sessão, centralizados."""

    def __init__(
        self,
        session_id: str,
        label: str,
        status: str,
        indicator_style: str = STYLE_SEMAPHORE,
        opacity: float = 1.0,
        parent=None,
    ):
        super().__init__(parent)
        self.session_id = session_id
        self._label = label
        self._message: str | None = None
        self._usage: dict | None = None
        self._opacity = opacity

        layout = QVBoxLayout(self)
        layout.setContentsMargins(CARD_PADDING, CARD_PADDING, CARD_PADDING, CARD_PADDING)
        layout.setSpacing(COLUMN_SPACING)

        # luzes criadas primeiro pra saber a largura antes de fixar o título
        self.lights = LightColumn(session_id, status, parent=self)
        self.lights.set_style(indicator_style)
        self.lights.set_opacity(opacity)

        self.title = _TitleLabel(self.lights.width(), self)
        self.title.set_text(label)
        self.title.set_status_color(status)
        layout.addWidget(self.title, alignment=Qt.AlignmentFlag.AlignHCenter)

        layout.addWidget(self.lights, alignment=Qt.AlignmentFlag.AlignHCenter)

    @property
    def status(self) -> str:
        return self.lights.status

    def set_style(self, indicator_style: str) -> None:
        self.lights.set_style(indicator_style)
        self.title.set_width(self.lights.width())

    def set_opacity(self, opacity: float) -> None:
        if opacity == self._opacity:
            return
        self._opacity = opacity
        self.lights.set_opacity(opacity)
        self.update()

    def paintEvent(self, event) -> None:
        # card individual da sessão (borda + fundo levemente mais claro que o
        # painel), imitando as sub-caixas por sessão dentro do painel único
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(0, 0, -1, -1)
        # preenchimento em CompositionMode_Source (substitui pixel) em vez de
        # SourceOver (padrão, mistura): o card cobre o painel logo abaixo, e
        # ambos são translúcidos — misturar duas camadas translúcidas soma o
        # alpha (~35% + 35% do resto vira ~58% efetivo), fazendo o card
        # aparecer como um retângulo nitidamente mais opaco em vez de se
        # misturar. Substituir garante que o alpha final seja exatamente o
        # configurado, igual ao resto do painel.
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_bg_color(CARD_BG_RGB, self._opacity))
        painter.drawRoundedRect(rect, CARD_CORNER_RADIUS, CARD_CORNER_RADIUS)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

        painter.setPen(QPen(_with_alpha_factor(CARD_BORDER_COLOR, self._opacity), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect, CARD_CORNER_RADIUS, CARD_CORNER_RADIUS)

        # linha fina separando o título do semáforo, como na referência;
        # fica a CARD_PADDING abaixo do título, simétrico ao respiro acima
        # dele, para o texto ficar centralizado na faixa de cabeçalho
        divider_y = self.title.geometry().bottom() + CARD_PADDING
        painter.setPen(QPen(_with_alpha_factor(CARD_DIVIDER_COLOR, self._opacity), 1))
        painter.drawLine(
            QPoint(CARD_PADDING - 4, round(divider_y)), QPoint(self.width() - CARD_PADDING + 4, round(divider_y))
        )

        painter.end()
        super().paintEvent(event)

    def event(self, event) -> bool:
        # substitui o QToolTip nativo pelo nosso popup sempre-no-topo (ver
        # _AlwaysOnTopTooltip) — o nativo fica atrás do painel em vários
        # WMs/compositores por causa do WindowStaysOnTopHint do painel.
        if event.type() == QEvent.Type.ToolTip:
            text = self.toolTip()
            if text:
                _AlwaysOnTopTooltip.show_text(text)
            event.accept()
            return True
        if event.type() in (QEvent.Type.Leave, QEvent.Type.Hide):
            _AlwaysOnTopTooltip.hide_tooltip()
        return super().event(event)

    def update_session(
        self, label: str, status: str, message: str | None, usage: dict | None = None
    ) -> None:
        self._label = label
        self._message = message
        self._usage = usage
        self.title.set_text(label)
        self.title.set_status_color(status)
        self.lights.set_status(status)
        self.lights.set_usage(usage.get("total_tokens") if usage else None)
        self.setToolTip(self._tooltip_text())

    def _tooltip_text(self) -> str:
        lines = [self._label]
        if self._message:
            lines.append(f"\n{self._message}")
        usage_line = self._usage_text()
        if usage_line:
            lines.append(f"\n{usage_line}")
        return "\n".join(lines)

    def _usage_text(self) -> str | None:
        usage = self._usage
        if not usage:
            return None
        parts = []
        total_tokens = usage.get("total_tokens")
        if total_tokens is not None:
            parts.append(f"Tokens acumulados: {total_tokens:,}")
        used_pct = usage.get("used_percentage")
        if used_pct is not None:
            parts.append(f"Contexto atual: {round(used_pct)}%")
        cost = usage.get("total_cost_usd")
        if cost is not None:
            parts.append(f"Custo: ${cost:.4f}")
        return " · ".join(parts) if parts else None


class SemaphorePanel(QWidget):
    moved = pyqtSignal(QPoint)
    right_clicked = pyqtSignal()

    def __init__(self):
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self._columns: dict[str, _SessionColumn] = {}
        self._drag_offset: QPoint | None = None
        self._usage_enabled = True
        self._usage_thresholds: list = []
        self._indicator_style = STYLE_SEMAPHORE
        self._opacity = DEFAULT_PANEL_OPACITY_PERCENT / 100.0

        # o painel em si tem um layout fixo (nunca trocado) com uma margem só
        # e um único filho: o "flow", cujo layout interno (lado a lado vs
        # empilhado) é recriado do zero a cada troca de estilo — trocar o
        # layout instalado diretamente em `self` não é seguro (ver
        # _rebuild_layout) porque widgets Qt não permitem duas chamadas de
        # setLayout no mesmo objeto.
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(
            SHADOW_MARGIN + PADDING, SHADOW_MARGIN + PADDING, SHADOW_MARGIN + PADDING, SHADOW_MARGIN + PADDING
        )
        self._layout.setSpacing(0)
        self._flow: QWidget | None = None
        self._flow_layout: QHBoxLayout | QVBoxLayout | None = None
        self._rebuild_layout(vertical=False)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(28)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(0, 0, 0, 170))
        self.setGraphicsEffect(shadow)

        self._anchor_right = False
        self._resize_start_right = 0
        self._anchor_bottom = False
        self._resize_start_bottom = 0

        self._resize_animation = QVariantAnimation(self)
        self._resize_animation.setDuration(RESIZE_ANIMATION_MS)
        self._resize_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._resize_animation.valueChanged.connect(self._apply_resize)

        self._resize_to_content()

    # -- gerenciamento de sessões -------------------------------------------------
    def _rebuild_layout(self, vertical: bool) -> None:
        # troca a direção do "flow" (lado a lado vs empilhado) recriando o
        # container inteiro em vez de trocar o layout instalado nele — Qt não
        # permite widget.setLayout() duas vezes no mesmo objeto, e uma
        # tentativa anterior de desanexar o layout antigo pra um QWidget()
        # descartável causava um bug real: sem nenhuma referência Python viva,
        # esse widget temporário era coletado pelo GC quase imediatamente,
        # destruindo em cascata os cards de sessão que tinham acabado de ser
        # reparentados pra ele.
        old_flow = self._flow
        new_flow = QWidget(self)
        new_layout = QVBoxLayout(new_flow) if vertical else QHBoxLayout(new_flow)
        new_layout.setContentsMargins(0, 0, 0, 0)
        new_layout.setSpacing(DOT_STYLE_CARD_GAP if vertical else COLUMN_GAP)
        for column in self._columns.values():
            new_layout.addWidget(column)  # reparenta automaticamente pro novo flow
        self._flow = new_flow
        self._flow_layout = new_layout
        self._layout.addWidget(new_flow)
        if old_flow is not None:
            self._layout.removeWidget(old_flow)
            old_flow.deleteLater()

    def set_usage_config(self, enabled: bool, thresholds: list, indicator_style: str = STYLE_SEMAPHORE) -> None:
        self._usage_enabled = enabled
        self._usage_thresholds = thresholds
        style_changed = indicator_style != self._indicator_style
        self._indicator_style = indicator_style
        if style_changed:
            self._rebuild_layout(vertical=indicator_style == STYLE_DOT)
        for column in self._columns.values():
            column.lights.set_show_usage(enabled)
            column.lights.set_thresholds(thresholds)
            column.set_style(indicator_style)
        self._resize_to_content()

    def set_panel_opacity(self, percent: int) -> None:
        opacity = max(MIN_PANEL_OPACITY_PERCENT, min(100, percent)) / 100.0
        if opacity == self._opacity:
            return
        self._opacity = opacity
        for column in self._columns.values():
            column.set_opacity(opacity)
        self.update()

    def upsert_session(
        self,
        session_id: str,
        label: str,
        status: str,
        message: str | None = None,
        usage: dict | None = None,
    ) -> None:
        column = self._columns.get(session_id)
        if column is None:
            column = _SessionColumn(
                session_id,
                label,
                status,
                indicator_style=self._indicator_style,
                opacity=self._opacity,
                parent=self,
            )
            column.lights.set_show_usage(self._usage_enabled)
            column.lights.set_thresholds(self._usage_thresholds)
            self._flow_layout.addWidget(column)
            self._columns[session_id] = column
        column.update_session(label, status, message, usage)
        self._resize_to_content()

    def remove_session(self, session_id: str) -> None:
        column = self._columns.pop(session_id, None)
        if column is None:
            return
        self._flow_layout.removeWidget(column)
        column.deleteLater()
        self._resize_to_content()

    def statuses(self) -> list[str]:
        return [c.status for c in self._columns.values()]

    def _resize_to_content(self) -> None:
        if self._columns:
            count = len(self._columns)
            if self._indicator_style == STYLE_DOT:
                # empilhado: largura fixa (um card largo), altura cresce com o nº de sessões
                width = 2 * PADDING + DOT_CARD_WIDTH
                height = (
                    2 * PADDING
                    + sum(c.sizeHint().height() for c in self._columns.values())
                    + (count - 1) * DOT_STYLE_CARD_GAP
                )
            else:
                # lado a lado: largura cresce com o nº de sessões, altura fixa (um card)
                width = 2 * PADDING + count * CARD_WIDTH + (count - 1) * COLUMN_GAP
                height = 2 * PADDING + max(c.sizeHint().height() for c in self._columns.values())
        else:
            width = PLACEHOLDER_WIDTH
            height = 2 * PADDING + CONTENT_HEIGHT
        target = QSize(int(width) + 2 * SHADOW_MARGIN, int(height) + 2 * SHADOW_MARGIN)

        if not self.isVisible() or self.size() == target:
            self._resize_animation.stop()
            self.setFixedSize(target)
            return

        self._resize_animation.stop()
        self._anchor_right = self._is_near_right_edge()
        self._resize_start_right = self.x() + self.width()
        self._anchor_bottom = self._is_near_bottom_edge()
        self._resize_start_bottom = self.y() + self.height()
        self._resize_animation.setStartValue(self.size())
        self._resize_animation.setEndValue(target)
        self._resize_animation.start()

    def _apply_resize(self, size: QSize) -> None:
        # por padrão o Qt cresce/encolhe mantendo o canto superior esquerdo
        # fixo (setFixedSize não mexe em x/y). Se o painel estiver ancorado
        # perto da borda direita/inferior da tela, isso faz ele "fugir" do
        # canto ao crescer (ou descolar dele ao encolher) — por isso, nesse
        # caso, recalculamos x/y pra manter aquela borda parada e crescer
        # pro lado oposto (esquerda/cima).
        self.setFixedSize(size)
        x = self._resize_start_right - size.width() if self._anchor_right else self.x()
        y = self._resize_start_bottom - size.height() if self._anchor_bottom else self.y()
        self.move(x, y)

    def _is_near_right_edge(self) -> bool:
        screen = QGuiApplication.screenAt(self.frameGeometry().center()) or QGuiApplication.primaryScreen()
        if screen is None:
            return False
        bounds = screen.availableGeometry()
        dist_left = self.x() - bounds.left()
        dist_right = bounds.right() - (self.x() + self.width())
        return dist_right < dist_left

    def _is_near_bottom_edge(self) -> bool:
        screen = QGuiApplication.screenAt(self.frameGeometry().center()) or QGuiApplication.primaryScreen()
        if screen is None:
            return False
        bounds = screen.availableGeometry()
        dist_top = self.y() - bounds.top()
        dist_bottom = bounds.bottom() - (self.y() + self.height())
        return dist_bottom < dist_top

    def _panel_rect(self):
        return self.rect().adjusted(SHADOW_MARGIN, SHADOW_MARGIN, -SHADOW_MARGIN, -SHADOW_MARGIN)

    # -- aparência -----------------------------------------------------------
    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        panel_rect = self._panel_rect()

        gradient = QLinearGradient(
            panel_rect.left(), panel_rect.top(), panel_rect.left(), panel_rect.bottom()
        )
        gradient.setColorAt(0.0, _bg_color((34, 34, 39), self._opacity))
        gradient.setColorAt(1.0, _bg_color((18, 18, 22), self._opacity))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(gradient)
        painter.drawRoundedRect(panel_rect, CORNER_RADIUS, CORNER_RADIUS)

        painter.setPen(_with_alpha_factor(QColor(255, 255, 255, 18), self._opacity))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(panel_rect.adjusted(0, 0, -1, -1), CORNER_RADIUS, CORNER_RADIUS)

        if not self._columns:
            painter.setPen(QColor("#8a8a8e"))
            font = painter.font()
            font.setPointSize(8)
            painter.setFont(font)
            painter.drawText(panel_rect, Qt.AlignmentFlag.AlignCenter, "Sem sessões monitoradas")

        painter.end()

    # -- arrastar / ocultar -----------------------------------------------------------
    def mousePressEvent(self, event) -> None:
        _AlwaysOnTopTooltip.hide_tooltip()
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        elif event.button() == Qt.MouseButton.RightButton:
            self.right_clicked.emit()

    def mouseMoveEvent(self, event) -> None:
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)

    def hideEvent(self, event) -> None:
        _AlwaysOnTopTooltip.hide_tooltip()
        super().hideEvent(event)

    def mouseReleaseEvent(self, _event) -> None:
        if self._drag_offset is not None:
            self.moved.emit(self.pos())
        self._drag_offset = None
