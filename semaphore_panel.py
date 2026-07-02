"""Painel único, flutuante e arrastável que agrupa um semáforo compacto por
sessão lado a lado (em vez de abrir uma janela separada para cada uma)."""
from PyQt6.QtCore import QPoint, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QLinearGradient, QPainter
from PyQt6.QtWidgets import QGraphicsDropShadowEffect, QHBoxLayout, QWidget

from light_column import COLUMN_WIDTH, CONTENT_HEIGHT, LightColumn

PADDING = 9
COLUMN_GAP = 8
PLACEHOLDER_WIDTH = 140
SHADOW_MARGIN = 16  # espaço em volta do painel só para a sombra suave renderizar
CORNER_RADIUS = 16


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

        self._columns: dict[str, LightColumn] = {}
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

        self._resize_to_content()

    # -- gerenciamento de sessões -------------------------------------------------
    def upsert_session(self, session_id: str, label: str, status: str) -> None:
        column = self._columns.get(session_id)
        if column is None:
            column = LightColumn(session_id, label, status, parent=self)
            column.setToolTip(label)
            self._layout.addWidget(column)
            self._columns[session_id] = column
            self._resize_to_content()
        else:
            column.set_label(label)
            column.set_status(status)

    def remove_session(self, session_id: str) -> None:
        column = self._columns.pop(session_id, None)
        if column is not None:
            self._layout.removeWidget(column)
            column.deleteLater()
            self._resize_to_content()

    def statuses(self) -> list[str]:
        return [c.status for c in self._columns.values()]

    def _resize_to_content(self) -> None:
        if self._columns:
            count = len(self._columns)
            width = 2 * PADDING + count * COLUMN_WIDTH + (count - 1) * COLUMN_GAP
        else:
            width = PLACEHOLDER_WIDTH
        height = 2 * PADDING + CONTENT_HEIGHT
        self.setFixedSize(int(width) + 2 * SHADOW_MARGIN, int(height) + 2 * SHADOW_MARGIN)

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
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        elif event.button() == Qt.MouseButton.RightButton:
            self.right_clicked.emit()

    def mouseMoveEvent(self, event) -> None:
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)

    def mouseReleaseEvent(self, _event) -> None:
        if self._drag_offset is not None:
            self.moved.emit(self.pos())
        self._drag_offset = None
