"""Janela de configurações (personagem, som do mascote, mascote, beep de alerta)."""
from typing import Callable

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from config import Config
from mascot import MascotWidget, list_agents

PREVIEW_SIZE = (144, 108)

DIALOG_STYLE = """
QDialog {
    background-color: #1c1c20;
}
QLabel {
    color: #e6e6ea;
}
QLabel#agentName {
    font-size: 13pt;
    font-weight: 600;
    color: #f2f2f5;
}
QLabel#hint {
    color: #8a8a92;
    font-size: 8pt;
}
QCheckBox {
    color: #d8d8dc;
    padding: 2px 0;
}
QPushButton#arrow {
    background-color: #2b2b31;
    border: 1px solid #3a3a42;
    border-radius: 18px;
    color: #e6e6ea;
    font-size: 14pt;
    min-width: 36px;
    min-height: 36px;
}
QPushButton#arrow:hover {
    background-color: #35353d;
}
QPushButton#arrow:pressed {
    background-color: #201d18;
}
QWidget#previewCard {
    background-color: #101013;
    border: 1px solid #3a3a42;
    border-radius: 14px;
}
QDialogButtonBox QPushButton {
    background-color: #2b2b31;
    border: 1px solid #3a3a42;
    border-radius: 6px;
    color: #e6e6ea;
    padding: 5px 16px;
}
QDialogButtonBox QPushButton:hover {
    background-color: #35353d;
}
QTabWidget::pane {
    border: 1px solid #2b2b31;
    border-radius: 8px;
    top: -1px;
}
QTabBar::tab {
    background-color: #201f24;
    color: #b0b0b8;
    padding: 6px 14px;
    border: 1px solid #2b2b31;
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
}
QTabBar::tab:selected {
    background-color: #2b2b31;
    color: #f2f2f5;
}
QTabBar::tab:hover {
    background-color: #2b2b31;
}
"""


class _ThresholdRow(QWidget):
    """Uma linha do editor de limiares: quantidade de tokens + cor + remover."""

    def __init__(
        self,
        tokens: int,
        color: str,
        on_change: Callable[[], None],
        on_remove: Callable[["_ThresholdRow"], None],
        parent=None,
    ):
        super().__init__(parent)
        self._on_change = on_change
        self._on_remove = on_remove
        self._color = color

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)

        self._spin = QSpinBox(self)
        self._spin.setRange(1_000, 2_000_000)
        self._spin.setSingleStep(10_000)
        self._spin.setSuffix(" tokens")
        self._spin.setValue(tokens)
        self._spin.valueChanged.connect(lambda _v: self._on_change())
        row.addWidget(self._spin, 1)

        self._color_button = QPushButton(self)
        self._color_button.setFixedSize(30, 22)
        self._apply_button_color()
        self._color_button.clicked.connect(self._pick_color)
        row.addWidget(self._color_button)

        remove_button = QPushButton("✕", self)
        remove_button.setFixedSize(22, 22)
        remove_button.clicked.connect(lambda: self._on_remove(self))
        row.addWidget(remove_button)

    def _apply_button_color(self) -> None:
        self._color_button.setStyleSheet(
            f"background-color: {self._color}; border: 1px solid #3a3a42; border-radius: 4px;"
        )

    def _pick_color(self) -> None:
        chosen = QColorDialog.getColor(QColor(self._color), self, "Escolha a cor")
        if chosen.isValid():
            self._color = chosen.name()
            self._apply_button_color()
            self._on_change()

    def value(self) -> list:
        return [self._spin.value(), self._color]


class SettingsDialog(QDialog):
    def __init__(
        self,
        config: Config,
        on_change: Callable[[Config], None],
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Configurações — Semáforo de Status")
        self.setStyleSheet(DIALOG_STYLE)
        self._config = config
        self._on_change = on_change

        self._agents = list_agents()
        self._agent_index = self._agents.index(config.mascot) if config.mascot in self._agents else 0

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 16)

        tabs = QTabWidget(self)
        tabs.addTab(self._build_mascot_tab(), "Mascote")
        tabs.addTab(self._build_alerts_tab(), "Alertas")
        tabs.addTab(self._build_usage_tab(), "Uso de tokens")
        layout.addWidget(tabs)

        hint = QLabel("As mudanças aplicam na hora, sem precisar reiniciar.", self)
        hint.setObjectName("hint")
        layout.addWidget(hint)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.close)
        buttons.button(QDialogButtonBox.StandardButton.Close).clicked.connect(self.close)
        layout.addWidget(buttons)

    # -- aba: mascote -------------------------------------------------
    def _build_mascot_tab(self) -> QWidget:
        config = self._config
        tab = QWidget(self)
        layout = QVBoxLayout(tab)
        layout.setSpacing(12)
        layout.setContentsMargins(4, 12, 4, 4)

        layout.addLayout(self._build_carousel())

        self._mascot_enabled_check = QCheckBox("Mostrar mascote", self)
        self._mascot_enabled_check.setChecked(config.mascot_enabled)
        self._mascot_enabled_check.toggled.connect(self._on_mascot_enabled_toggled)
        layout.addWidget(self._mascot_enabled_check)

        self._mascot_sounds_check = QCheckBox("Som do mascote", self)
        self._mascot_sounds_check.setChecked(config.mascot_sounds_enabled)
        self._mascot_sounds_check.toggled.connect(self._on_mascot_sounds_toggled)
        layout.addWidget(self._mascot_sounds_check)

        layout.addLayout(self._build_percent_row(
            "Tamanho do mascote", config.mascot_scale, self._on_mascot_scale_changed
        ))
        layout.addStretch(1)
        return tab

    # -- aba: alertas -------------------------------------------------
    def _build_alerts_tab(self) -> QWidget:
        config = self._config
        tab = QWidget(self)
        layout = QVBoxLayout(tab)
        layout.setSpacing(12)
        layout.setContentsMargins(4, 12, 4, 4)

        self._alert_beep_check = QCheckBox("Beep de alerta (erro)", self)
        self._alert_beep_check.setChecked(config.alert_beep_enabled)
        self._alert_beep_check.toggled.connect(self._on_alert_beep_toggled)
        layout.addWidget(self._alert_beep_check)

        self._notification_check = QCheckBox("Notificação do sistema (erro)", self)
        self._notification_check.setChecked(config.notification_enabled)
        self._notification_check.toggled.connect(self._on_notification_toggled)
        layout.addWidget(self._notification_check)

        layout.addLayout(self._build_timing_row(
            "Revezamento entre sessões (s)", config.mascot_rotation_seconds, self._on_rotation_changed
        ))
        layout.addLayout(self._build_timing_row(
            "Última mensagem ociosa (s)", config.mascot_idle_last_seconds, self._on_idle_last_changed
        ))
        layout.addLayout(self._build_char_limit_row(
            "Caracteres no balão antes de truncar", config.mascot_message_limit, self._on_message_limit_changed
        ))
        layout.addStretch(1)
        return tab

    # -- aba: uso de tokens -------------------------------------------------
    def _build_usage_tab(self) -> QWidget:
        tab = QWidget(self)
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(4, 12, 4, 4)
        layout.addLayout(self._build_usage_section())
        layout.addStretch(1)
        return tab

    # -- carrossel de personagem -------------------------------------------------
    def _build_carousel(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(12)

        prev_button = QPushButton("◀", self)
        prev_button.setObjectName("arrow")
        prev_button.clicked.connect(lambda: self._step_agent(-1))
        row.addWidget(prev_button)

        card = QWidget(self)
        card.setObjectName("previewCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(12, 12, 12, 10)
        card_layout.setSpacing(8)

        self._preview = MascotWidget(self._agents[self._agent_index], sound_enabled=False, parent=card, size=PREVIEW_SIZE)
        card_layout.addWidget(self._preview, alignment=Qt.AlignmentFlag.AlignHCenter)

        self._agent_name_label = QLabel(self._agents[self._agent_index], card)
        self._agent_name_label.setObjectName("agentName")
        self._agent_name_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        card_layout.addWidget(self._agent_name_label)

        row.addWidget(card, stretch=1)

        next_button = QPushButton("▶", self)
        next_button.setObjectName("arrow")
        next_button.clicked.connect(lambda: self._step_agent(1))
        row.addWidget(next_button)

        return row

    def _build_timing_row(self, label_text: str, value: float, on_change: Callable[[float], None]) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(QLabel(label_text, self))
        row.addStretch(1)
        spin = QDoubleSpinBox(self)
        spin.setRange(1.0, 60.0)
        spin.setSingleStep(0.5)
        spin.setDecimals(1)
        spin.setValue(value)
        spin.valueChanged.connect(on_change)
        row.addWidget(spin)
        return row

    def _build_char_limit_row(self, label_text: str, value: int, on_change: Callable[[int], None]) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(QLabel(label_text, self))
        row.addStretch(1)
        spin = QSpinBox(self)
        spin.setRange(30, 1000)
        spin.setSingleStep(10)
        spin.setValue(value)
        spin.valueChanged.connect(on_change)
        row.addWidget(spin)
        return row

    def _build_percent_row(self, label_text: str, value: int, on_change: Callable[[int], None]) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(QLabel(label_text, self))
        row.addStretch(1)
        spin = QSpinBox(self)
        spin.setRange(50, 200)
        spin.setSingleStep(10)
        spin.setSuffix("%")
        spin.setValue(value)
        spin.valueChanged.connect(on_change)
        row.addWidget(spin)
        return row

    def _build_usage_section(self) -> QVBoxLayout:
        section = QVBoxLayout()
        section.setSpacing(6)

        self._usage_bar_check = QCheckBox("Mostrar barra de uso de tokens", self)
        self._usage_bar_check.setChecked(self._config.usage_bar_enabled)
        self._usage_bar_check.toggled.connect(self._on_usage_bar_toggled)
        section.addWidget(self._usage_bar_check)

        hint = QLabel("Limiares de cor (tokens acumulados na sessão):", self)
        hint.setObjectName("hint")
        section.addWidget(hint)

        self._threshold_rows: list[_ThresholdRow] = []
        self._threshold_list_layout = QVBoxLayout()
        self._threshold_list_layout.setSpacing(4)
        section.addLayout(self._threshold_list_layout)

        for tokens, color in self._config.usage_thresholds:
            self._add_threshold_row(tokens, color, emit=False)

        add_button = QPushButton("+ Adicionar limiar", self)
        add_button.clicked.connect(lambda: self._add_threshold_row(100_000, "#32d74b"))
        section.addWidget(add_button)

        return section

    def _add_threshold_row(self, tokens: int, color: str, emit: bool = True) -> None:
        row = _ThresholdRow(tokens, color, on_change=self._on_thresholds_changed, on_remove=self._remove_threshold_row, parent=self)
        self._threshold_rows.append(row)
        self._threshold_list_layout.addWidget(row)
        if emit:
            self._on_thresholds_changed()

    def _remove_threshold_row(self, row: "_ThresholdRow") -> None:
        if len(self._threshold_rows) <= 1:
            return  # mantém pelo menos um limiar — sem isso a barra perde a referência de "cheio"
        self._threshold_rows.remove(row)
        self._threshold_list_layout.removeWidget(row)
        row.deleteLater()
        self._on_thresholds_changed()

    def _on_thresholds_changed(self) -> None:
        self._config.usage_thresholds = [row.value() for row in self._threshold_rows]
        self._emit_change()

    def _on_usage_bar_toggled(self, checked: bool) -> None:
        self._config.usage_bar_enabled = checked
        self._emit_change()

    def _step_agent(self, direction: int) -> None:
        self._agent_index = (self._agent_index + direction) % len(self._agents)
        name = self._agents[self._agent_index]
        self._preview.set_agent(name)
        self._agent_name_label.setText(name)
        self._config.mascot = name
        self._emit_change()

    # -- toggles -------------------------------------------------
    def _emit_change(self) -> None:
        self._on_change(self._config)

    def _on_mascot_enabled_toggled(self, checked: bool) -> None:
        self._config.mascot_enabled = checked
        self._emit_change()

    def _on_mascot_sounds_toggled(self, checked: bool) -> None:
        self._config.mascot_sounds_enabled = checked
        self._emit_change()

    def _on_mascot_scale_changed(self, value: int) -> None:
        self._config.mascot_scale = value
        self._emit_change()

    def _on_alert_beep_toggled(self, checked: bool) -> None:
        self._config.alert_beep_enabled = checked
        self._emit_change()

    def _on_notification_toggled(self, checked: bool) -> None:
        self._config.notification_enabled = checked
        self._emit_change()

    def _on_rotation_changed(self, value: float) -> None:
        self._config.mascot_rotation_seconds = value
        self._emit_change()

    def _on_idle_last_changed(self, value: float) -> None:
        self._config.mascot_idle_last_seconds = value
        self._emit_change()

    def _on_message_limit_changed(self, value: int) -> None:
        self._config.mascot_message_limit = value
        self._emit_change()
