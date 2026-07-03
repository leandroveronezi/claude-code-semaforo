"""Mascote único e flutuante, numa janela própria (transparente, sempre no
topo, arrastável), que reflete o humor agregado de todas as sessões
monitoradas — em vez de um mascote por sessão.

Prioridade de humor: erro > trabalhando > ocioso (mesma lógica do ícone da
bandeja). Quando há mais de uma sessão no mesmo nível:
- erro/trabalhando: revezamos entre todas em loop, por ordem de chegada
  (a que virou erro/working há mais tempo aparece primeiro).
- ocioso: é só uma notificação passageira (nada urgente) — cada sessão que
  termina entra numa fila consumida uma única vez, a última entrada fica
  mais tempo em tela, e depois some tudo até a próxima chegar.
Em ambos os casos, passar o mouse por cima pausa a contagem.

O mascote fica ancorado no ponto onde foi arrastado (self._anchor); é a
janela inteira que é recalculada ao redor dele — não o contrário — pra o
personagem nunca "pular" quando o balão aparece/cresce. O balão cresce pro
lado que tiver espaço na tela: acima por padrão, ao lado se o mascote
estiver perto do topo, espelhado se estiver perto da borda direita/esquerda."""
from PyQt6.QtCore import QPoint, QRect, QSettings, QSize, Qt, QTimer
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import QWidget

from config import Config
from mascot import MascotWidget
from speech_bubble import TAIL_HEIGHT as BUBBLE_TAIL_LENGTH
from speech_bubble import SpeechBubble

SETTINGS_KEY = "mascot/pos"
MARGIN = 12  # respiro entre o conteúdo (mascote+balão) e a borda da janela
GAP = 2  # distância entre o corpo do mascote e o corpo do balão (o rabinho preenche visualmente)
DEFAULT_POS = QPoint(160, 160)
RAISE_INTERVAL_MS = 700  # ver comentário em _AlwaysOnTopTooltip (semaphore_panel.py)
MASCOT_SIZE = (144, 108)

TICK_MS = 250  # granularidade do relógio de rotação (permite pausar no hover sem perder precisão)

Entry = tuple[str, "str | None", "str | None"]  # (label, message, activity)


class MascotOverlay(QWidget):
    def __init__(self, config: Config):
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            # o painel usa só as três flags acima e nunca some; a diferença é
            # que ninguém arrasta o mascote com a mesma frequência, e vários
            # WMs retiram (unmap) janelas "Tool" sem interação recente assim
            # que outra janela é ativada. Bypass tira a janela do controle do
            # WM (deixa de ser gerenciada/escondida por ele), igual o popup
            # de tooltip (Qt.WindowType.ToolTip) já faz por convenção.
            | Qt.WindowType.X11BypassWindowManagerHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self._drag_offset: QPoint | None = None
        self._hovering = False

        self._tier = "idle"  # "error" | "working" | "idle" — o que está em tela agora
        self._last_pose_tier = "idle"  # pra saber quando aplicar o gesto de alívio (erro -> ocioso)
        self._error_entries: list[Entry] = []
        self._working_entries: list[Entry] = []
        self._rotation_index = 0
        self._idle_queue: list[tuple[str, "str | None"]] = []  # (label, message), consumida uma vez
        self._elapsed_ms = 0
        self._rotation_ms = int(config.mascot_rotation_seconds * 1000)
        self._idle_last_ms = int(config.mascot_idle_last_seconds * 1000)
        self._current_duration_ms = self._rotation_ms

        self._raise_timer = QTimer(self)
        self._raise_timer.setInterval(RAISE_INTERVAL_MS)
        self._raise_timer.timeout.connect(self.raise_)

        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(TICK_MS)
        self._tick_timer.timeout.connect(self._on_tick)

        self._settings = QSettings("SemaforoStatus", "Posicoes")
        saved_pos = self._settings.value(SETTINGS_KEY)
        self._anchor = saved_pos if isinstance(saved_pos, QPoint) else DEFAULT_POS

        # sem layout: mascote e balão são posicionados manualmente em
        # _relayout(), porque a posição relativa entre os dois muda conforme
        # a borda da tela mais próxima do mascote.
        self.bubble = SpeechBubble(self)
        self.mascot = MascotWidget(config.mascot, config.mascot_sounds_enabled, self, size=MASCOT_SIZE)

        self._relayout()

    # -- entrada de dados (SessionManager) -----------------------------------------
    def sync(self, error_entries: list[Entry], working_entries: list[Entry]) -> None:
        """Chamado a cada varredura de sessões: atualiza o elenco atual de
        erro/trabalhando. Não reinicia a contagem de rotação se o nível
        (tier) em tela continuar o mesmo — só a composição da lista muda."""
        self._error_entries = error_entries
        self._working_entries = working_entries
        tier = "error" if error_entries else "working" if working_entries else "idle"
        if tier != self._tier:
            self._enter_tier(tier)
        elif tier != "idle":
            entries = self._entries_for(tier)
            if entries:
                self._rotation_index %= len(entries)
            self._show_current()

    def enqueue_idle(self, label: str, message: "str | None") -> None:
        """Sessão acabou de ficar ociosa: entra na fila de notificações,
        mostrada uma única vez (não fica em loop como erro/working)."""
        self._idle_queue.append((label, message))
        if self._tier != "idle":
            return
        if len(self._idle_queue) == 1:
            self._elapsed_ms = 0
            self._show_current()
        else:
            # o item em exibição deixou de ser o último da fila -> duração
            # normal (não a longa); se já passou do novo tempo, o próximo
            # tick avança pra ele. Não mexe no elapsed: não reinicia a conta.
            self._current_duration_ms = self._rotation_ms

    # -- motor de rotação -----------------------------------------------------------
    def _entries_for(self, tier: str) -> list[Entry]:
        if tier == "error":
            return self._error_entries
        if tier == "working":
            return self._working_entries
        return []

    def _enter_tier(self, tier: str) -> None:
        self._tier = tier
        self._rotation_index = 0
        self._elapsed_ms = 0
        self._show_current()

    def _show_current(self) -> None:
        if self._tier in ("error", "working"):
            entries = self._entries_for(self._tier)
            if not entries:
                self._apply_pose(self._tier, None)
                self.bubble.set_message(None)
                self.setToolTip("")
            else:
                self._rotation_index %= len(entries)
                label, message, activity = entries[self._rotation_index]
                self._apply_pose(self._tier, activity)
                self.bubble.set_message(message)
                self.setToolTip(self._tooltip_text(label, message))
            self._current_duration_ms = self._rotation_ms
        else:  # idle
            if not self._idle_queue:
                self._apply_pose("idle", None)
                self.bubble.set_message(None)
                self.setToolTip("")
            else:
                label, message = self._idle_queue[0]
                self._apply_pose("idle", None)
                self.bubble.set_message(message)
                self.setToolTip(self._tooltip_text(label, message))
                self._current_duration_ms = self._idle_last_ms if len(self._idle_queue) == 1 else self._rotation_ms
        self._relayout()

    def _apply_pose(self, tier: str, activity: "str | None") -> None:
        previous = self._last_pose_tier
        self._last_pose_tier = tier
        if tier == "idle" and previous == "error":
            self.mascot.play_relief(tier, activity)
        else:
            self.mascot.play_status(tier, activity)

    def _on_tick(self) -> None:
        if self._hovering:
            return
        if self._tier in ("error", "working"):
            if not self._entries_for(self._tier):
                return
        elif not self._idle_queue:
            return
        self._elapsed_ms += TICK_MS
        if self._elapsed_ms < self._current_duration_ms:
            return
        self._elapsed_ms = 0
        if self._tier in ("error", "working"):
            entries = self._entries_for(self._tier)
            self._rotation_index = (self._rotation_index + 1) % len(entries)
        else:
            self._idle_queue.pop(0)
        self._show_current()

    def _tooltip_text(self, label: str, message: "str | None") -> str:
        return f"{label}\n\n{message}" if message else label

    # -- posicionamento inteligente do balão -----------------------------------------------------------
    def _relayout(self) -> None:
        mascot_w, mascot_h = MASCOT_SIZE
        mascot_rect = QRect(self._anchor, QSize(mascot_w, mascot_h))

        screen = QGuiApplication.screenAt(mascot_rect.center()) or QGuiApplication.primaryScreen()
        screen_rect = screen.availableGeometry() if screen else QRect(0, 0, 3840, 2160)

        if not self.bubble.has_content:
            self.bubble.set_tail_side("bottom")
            union = mascot_rect.adjusted(-MARGIN, -MARGIN, MARGIN, MARGIN)
            self.setGeometry(union)
            self.mascot.move(mascot_rect.topLeft() - union.topLeft())
            return

        body = self.bubble.content_size()
        near_top = mascot_rect.top() - GAP - BUBBLE_TAIL_LENGTH - body.height() < screen_rect.top()

        if near_top:
            near_right = mascot_rect.right() + GAP + BUBBLE_TAIL_LENGTH + body.width() > screen_rect.right()
            self.bubble.set_tail_side("left" if near_right else "right")
            bubble_y = mascot_rect.center().y() - self.bubble.height() // 2
            bubble_x = (
                mascot_rect.left() - GAP - self.bubble.width()
                if near_right
                else mascot_rect.right() + GAP
            )
        else:
            self.bubble.set_tail_side("bottom")
            bubble_y = mascot_rect.top() - GAP - self.bubble.height()
            bubble_x = mascot_rect.center().x() - self.bubble.width() // 2
            bubble_x = min(bubble_x, screen_rect.right() - self.bubble.width())
            bubble_x = max(bubble_x, screen_rect.left())

        bubble_rect = QRect(QPoint(bubble_x, bubble_y), self.bubble.size())
        union = mascot_rect.united(bubble_rect).adjusted(-MARGIN, -MARGIN, MARGIN, MARGIN)
        self.setGeometry(union)
        self.mascot.move(mascot_rect.topLeft() - union.topLeft())
        self.bubble.move(bubble_rect.topLeft() - union.topLeft())

    # -- visibilidade -----------------------------------------------------------
    def set_visible_animated(self, visible: bool) -> None:
        if visible == self.isVisible():
            return
        if visible:
            self.show()
            self.raise_()
            self._raise_timer.start()
            self._tick_timer.start()
            self.mascot.play_intro()
        else:
            self._raise_timer.stop()
            self._tick_timer.stop()
            self.mascot.play_outro(on_finished=self.hide)

    def update_config(self, config: Config) -> None:
        self.mascot.set_agent(config.mascot)
        self.mascot.set_sound_enabled(config.mascot_sounds_enabled)
        self._rotation_ms = int(config.mascot_rotation_seconds * 1000)
        self._idle_last_ms = int(config.mascot_idle_last_seconds * 1000)

    # -- hover (pausa a rotação) -----------------------------------------------------------
    def enterEvent(self, event) -> None:
        self._hovering = True
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovering = False
        super().leaveEvent(event)

    # -- arrastar -----------------------------------------------------------
    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self._anchor

    def mouseMoveEvent(self, event) -> None:
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self._anchor = event.globalPosition().toPoint() - self._drag_offset
            self._relayout()

    def mouseReleaseEvent(self, _event) -> None:
        if self._drag_offset is not None:
            self._settings.setValue(SETTINGS_KEY, self._anchor)
        self._drag_offset = None
