"""Painel único, flutuante e arrastável que agrupa título + semáforo
compacto por sessão, lado a lado (em vez de abrir uma janela separada para
cada uma). O mascote é único e vive à parte, em mascot_overlay.py."""
from PyQt6.QtCore import QEasingCurve, QEvent, QPoint, QSize, Qt, QTimer, QVariantAnimation, pyqtSignal
from PyQt6.QtGui import QColor, QCursor, QFont, QFontMetrics, QGuiApplication, QLinearGradient, QPainter
from PyQt6.QtWidgets import QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from light_column import COLUMN_WIDTH, CONTENT_HEIGHT, LIGHT_COLORS, LightColumn

PADDING = 9
COLUMN_GAP = 8
COLUMN_SPACING = 4  # espaço vertical entre título e luzes dentro de uma sessão
RESIZE_ANIMATION_MS = 160
PLACEHOLDER_WIDTH = 140
SHADOW_MARGIN = 16  # espaço em volta do painel só para a sombra suave renderizar
CORNER_RADIUS = 16
TOOLTIP_OFFSET = QPoint(14, 18)  # deslocamento do cursor, como o tooltip nativo
RAISE_INTERVAL_MS = 300  # reforço periódico de empilhamento (ver _AlwaysOnTopTooltip)


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

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.setFixedWidth(COLUMN_WIDTH)
        font = self.font()
        font.setPointSize(6)
        font.setWeight(QFont.Weight.DemiBold)
        font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 102)
        self.setFont(font)

    def set_text(self, text: str) -> None:
        metrics = QFontMetrics(self.font())
        self.setText(metrics.elidedText(text, Qt.TextElideMode.ElideRight, self.width()))

    def set_status_color(self, status: str) -> None:
        color = LIGHT_COLORS.get(status, LIGHT_COLORS["idle"])
        self.setStyleSheet(f"color: {color.name()};")


class _SessionColumn(QWidget):
    """Empilha título e semáforo de uma sessão, centralizados."""

    def __init__(self, session_id: str, label: str, status: str, parent=None):
        super().__init__(parent)
        self.session_id = session_id
        self._label = label
        self._message: str | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(COLUMN_SPACING)

        self.title = _TitleLabel(self)
        self.title.set_text(label)
        self.title.set_status_color(status)
        layout.addWidget(self.title, alignment=Qt.AlignmentFlag.AlignHCenter)

        self.lights = LightColumn(session_id, status, parent=self)
        layout.addWidget(self.lights, alignment=Qt.AlignmentFlag.AlignHCenter)

    @property
    def status(self) -> str:
        return self.lights.status

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

    def update_session(self, label: str, status: str, message: str | None) -> None:
        self._label = label
        self._message = message
        self.title.set_text(label)
        self.title.set_status_color(status)
        self.lights.set_status(status)
        self.setToolTip(self._tooltip_text())

    def _tooltip_text(self) -> str:
        return f"{self._label}\n\n{self._message}" if self._message else self._label


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

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(
            SHADOW_MARGIN + PADDING, SHADOW_MARGIN + PADDING, SHADOW_MARGIN + PADDING, SHADOW_MARGIN + PADDING
        )
        self._layout.setSpacing(COLUMN_GAP)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(28)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(0, 0, 0, 170))
        self.setGraphicsEffect(shadow)

        self._anchor_right = False
        self._resize_start_right = 0

        self._resize_animation = QVariantAnimation(self)
        self._resize_animation.setDuration(RESIZE_ANIMATION_MS)
        self._resize_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._resize_animation.valueChanged.connect(self._apply_resize)

        self._resize_to_content()

    # -- gerenciamento de sessões -------------------------------------------------
    def upsert_session(self, session_id: str, label: str, status: str, message: str | None = None) -> None:
        column = self._columns.get(session_id)
        if column is None:
            column = _SessionColumn(session_id, label, status, parent=self)
            self._layout.addWidget(column)
            self._columns[session_id] = column
        column.update_session(label, status, message)
        self._resize_to_content()

    def remove_session(self, session_id: str) -> None:
        column = self._columns.pop(session_id, None)
        if column is None:
            return
        self._layout.removeWidget(column)
        column.deleteLater()
        self._resize_to_content()

    def statuses(self) -> list[str]:
        return [c.status for c in self._columns.values()]

    def _resize_to_content(self) -> None:
        if self._columns:
            count = len(self._columns)
            width = 2 * PADDING + count * COLUMN_WIDTH + (count - 1) * COLUMN_GAP
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
        self._resize_animation.setStartValue(self.size())
        self._resize_animation.setEndValue(target)
        self._resize_animation.start()

    def _apply_resize(self, size: QSize) -> None:
        # por padrão o Qt cresce/encolhe mantendo o canto esquerdo fixo
        # (setFixedSize não mexe em x/y). Se o painel estiver ancorado perto
        # da borda direita da tela, isso faz ele "fugir" do canto ao crescer
        # (ou descolar dele ao encolher) — por isso, nesse caso, recalculamos
        # x pra manter a borda direita parada e crescer/encolher pra esquerda.
        self.setFixedSize(size)
        if self._anchor_right:
            self.move(self._resize_start_right - size.width(), self.y())

    def _is_near_right_edge(self) -> bool:
        screen = QGuiApplication.screenAt(self.frameGeometry().center()) or QGuiApplication.primaryScreen()
        if screen is None:
            return False
        bounds = screen.availableGeometry()
        dist_left = self.x() - bounds.left()
        dist_right = bounds.right() - (self.x() + self.width())
        return dist_right < dist_left

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
        gradient.setColorAt(0.0, QColor(34, 34, 39, 240))
        gradient.setColorAt(1.0, QColor(18, 18, 22, 240))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(gradient)
        painter.drawRoundedRect(panel_rect, CORNER_RADIUS, CORNER_RADIUS)

        painter.setPen(QColor(255, 255, 255, 18))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(panel_rect.adjusted(0, 0, -1, -1), CORNER_RADIUS, CORNER_RADIUS)

        if not self._columns:
            painter.setPen(QColor("#8a8a8e"))
            font = painter.font()
            font.setPointSize(8)
            painter.setFont(font)
            painter.drawText(panel_rect, Qt.AlignmentFlag.AlignCenter, "Sem sessões monitoradas")
        else:
            self._draw_column_dividers(painter, panel_rect)

        painter.end()

    def _draw_column_dividers(self, painter: QPainter, panel_rect) -> None:
        widgets = [self._layout.itemAt(i).widget() for i in range(self._layout.count())]
        painter.setPen(QColor(255, 255, 255, 20))
        for left, right in zip(widgets, widgets[1:]):
            mid_x = (left.geometry().right() + right.geometry().left()) / 2
            painter.drawLine(
                int(mid_x), panel_rect.top() + 10, int(mid_x), panel_rect.bottom() - 10
            )

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
