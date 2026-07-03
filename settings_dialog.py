"""Janela de configurações (personagem, som do mascote, mascote, beep de alerta)."""
from typing import Callable

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
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
"""


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
        layout.setSpacing(14)
        layout.setContentsMargins(20, 20, 20, 16)

        layout.addLayout(self._build_carousel())

        self._mascot_enabled_check = QCheckBox("Mostrar mascote", self)
        self._mascot_enabled_check.setChecked(config.mascot_enabled)
        self._mascot_enabled_check.toggled.connect(self._on_mascot_enabled_toggled)
        layout.addWidget(self._mascot_enabled_check)

        self._mascot_sounds_check = QCheckBox("Som do mascote", self)
        self._mascot_sounds_check.setChecked(config.mascot_sounds_enabled)
        self._mascot_sounds_check.toggled.connect(self._on_mascot_sounds_toggled)
        layout.addWidget(self._mascot_sounds_check)

        self._alert_beep_check = QCheckBox("Beep de alerta (erro)", self)
        self._alert_beep_check.setChecked(config.alert_beep_enabled)
        self._alert_beep_check.toggled.connect(self._on_alert_beep_toggled)
        layout.addWidget(self._alert_beep_check)

        layout.addLayout(self._build_timing_row(
            "Revezamento entre sessões (s)", config.mascot_rotation_seconds, self._on_rotation_changed
        ))
        layout.addLayout(self._build_timing_row(
            "Última mensagem ociosa (s)", config.mascot_idle_last_seconds, self._on_idle_last_changed
        ))

        hint = QLabel("As mudanças aplicam na hora, sem precisar reiniciar.", self)
        hint.setObjectName("hint")
        layout.addWidget(hint)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.close)
        buttons.button(QDialogButtonBox.StandardButton.Close).clicked.connect(self.close)
        layout.addWidget(buttons)

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

    def _on_alert_beep_toggled(self, checked: bool) -> None:
        self._config.alert_beep_enabled = checked
        self._emit_change()

    def _on_rotation_changed(self, value: float) -> None:
        self._config.mascot_rotation_seconds = value
        self._emit_change()

    def _on_idle_last_changed(self, value: float) -> None:
        self._config.mascot_idle_last_seconds = value
        self._emit_change()
