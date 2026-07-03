"""Personagem animado (estilo MS Agent/Clippy) por sessão, sincronizado com o status.

Os assets em assets/mascot/<Nome>/ vêm do projeto clippy.js
(github.com/clippyjs/clippy.js): map.png é a planilha de sprites original e
agent.json é uma versão enxuta do agent.js de lá (framesize, quadros de
animação com duração/posição/som, e a resolução de qual animação usar pra
cada status — nem todo personagem tem os mesmos nomes de animação, ex.: o
Rover usa "Idle"/"Thinking"/"GetAttention" em vez de "Idle1_1"/"Processing"/
"Alert"). Ver README para detalhes/licença.
"""
import json
import random
import time
from pathlib import Path
from typing import Callable

from PyQt6.QtCore import QRectF, Qt, QTimer
from PyQt6.QtGui import QPainter, QPixmap
from PyQt6.QtWidgets import QWidget

from audio import play_sound

MASCOT_DIR = Path(__file__).resolve().parent / "assets" / "mascot"

MASCOT_WIDTH = 72
MASCOT_HEIGHT = 54

DEFAULT_AGENT = "Clippy"
DEFAULT_STATUS_ANIMATION = "idle"
ENTRANCE_ANIMATION = "Show"
EXIT_ANIMATION = "Hide"
RELIEF_ANIMATION = "Congratulate"  # gesto rápido ao sair de erro pra idle

# atividade (vinda do tool_name real, via hooks/status_hook.py) -> animação
# preferida, quando o personagem tiver essa animação pro status atual. Sem
# atividade reconhecida, cai no sorteio entre as candidatas do status.
ACTIVITY_ANIMATION = {
    "thinking": "Thinking",
    "writing": "Writing",
    "searching": "Searching",
    "processing": "Processing",
}
SOUND_COOLDOWN_SECONDS = 4.0
MIN_TRANSITION_FRAME_MS = 60  # piso pra Show/Hide não virarem um "flash" imperceptível

_agent_data_cache: dict[str, dict] = {}
_pixmap_cache: dict[str, QPixmap] = {}


def list_agents() -> list[str]:
    if not MASCOT_DIR.is_dir():
        return []
    return sorted(
        p.name for p in MASCOT_DIR.iterdir() if p.is_dir() and (p / "agent.json").exists()
    )


def _load_agent_data(name: str) -> dict:
    if name not in _agent_data_cache:
        path = MASCOT_DIR / name / "agent.json"
        _agent_data_cache[name] = json.loads(path.read_text(encoding="utf-8"))
    return _agent_data_cache[name]


def _load_pixmap(name: str) -> QPixmap:
    if name not in _pixmap_cache:
        _pixmap_cache[name] = QPixmap(str(MASCOT_DIR / name / "map.png"))
    return _pixmap_cache[name]


def _sound_path(agent_name: str, sound_id: str) -> Path:
    return MASCOT_DIR / agent_name / "sounds" / f"{sound_id}.wav"


class MascotWidget(QWidget):
    def __init__(
        self,
        agent_name: str = DEFAULT_AGENT,
        sound_enabled: bool = True,
        parent=None,
        size: tuple[int, int] = (MASCOT_WIDTH, MASCOT_HEIGHT),
    ):
        super().__init__(parent)
        self.setFixedSize(*size)
        # deixa os cliques passarem direto para o painel, como as luzes
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        self._sound_enabled = sound_enabled
        self._status = DEFAULT_STATUS_ANIMATION
        self._activity: str | None = None
        self._agent_name: str | None = None
        self._animation_name: str | None = None
        self._last_animation_by_status: dict[str, str] = {}
        self._sound_last_played: dict[str, float] = {}
        self._frames: list[dict] = []
        self._frame_index = 0
        self._loop = True
        # tocando Show/Hide (entrada/saída) — play_status() não deve interromper,
        # só guarda o status/atividade pendente pra aplicar assim que a transição acabar
        self._transitional = False
        self._pending_status: str | None = None
        self._pending_activity: str | None = None
        self._once_callback: Callable[[], None] | None = None

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._advance_frame)

        self.set_agent(agent_name)

    def set_agent(self, name: str) -> None:
        if name == self._agent_name:
            return
        self._agent_name = name
        self._data = _load_agent_data(name)
        self._pixmap = _load_pixmap(name)
        self._frame_width, self._frame_height = self._data["framesize"]
        self._animation_name = None  # força reresolver a animação do status atual
        self._transitional = False
        self.play_status(self._status, self._activity)

    def set_sound_enabled(self, enabled: bool) -> None:
        self._sound_enabled = enabled

    def play_status(self, status: str, activity: str | None = None) -> None:
        if self._transitional:
            self._pending_status = status
            self._pending_activity = activity
            return
        status_animations = self._data["status_animations"]
        candidates = status_animations.get(status) or status_animations[DEFAULT_STATUS_ANIMATION]
        animation_name = self._resolve_animation(status, activity, candidates)
        if status == self._status and animation_name == self._animation_name:
            return  # já tocando exatamente isso, não interrompe no meio
        self._status = status
        self._activity = activity
        self._animation_name = animation_name
        self._frames = self._data["animations"][animation_name]["frames"]
        self._frame_index = 0
        self._loop = True
        self._show_current_frame()

    def _resolve_animation(self, status: str, activity: str | None, candidates: list[str]) -> str:
        preferred = ACTIVITY_ANIMATION.get(activity)
        if preferred and preferred in candidates:
            return preferred
        return self._pick_animation(status, candidates)

    def play_intro(self, on_finished: Callable[[], None] | None = None) -> None:
        self._play_once_then_resume(ENTRANCE_ANIMATION, on_finished)

    def play_relief(
        self, status: str, activity: str | None = None, on_finished: Callable[[], None] | None = None
    ) -> None:
        """Gesto rápido de alívio/comemoração (ex.: saindo de erro pra idle)
        antes de assentar no status normal informado."""
        self._pending_status = status
        self._pending_activity = activity
        self._play_once_then_resume(RELIEF_ANIMATION, on_finished)

    def play_outro(self, on_finished: Callable[[], None]) -> None:
        self._play_once(EXIT_ANIMATION, on_finished)

    def _play_once_then_resume(self, animation_name: str, on_finished: Callable[[], None] | None) -> None:
        def _resume() -> None:
            self._transitional = False
            status = self._pending_status if self._pending_status is not None else self._status
            activity = self._pending_activity
            self._pending_status = None
            self._pending_activity = None
            self._animation_name = None  # força tocar o status mesmo se igual ao anterior
            self.play_status(status, activity)
            if on_finished:
                on_finished()

        self._play_once(animation_name, _resume)

    def _play_once(self, animation_name: str, on_finished: Callable[[], None] | None) -> None:
        self._transitional = True
        frames = self._data["animations"].get(animation_name, {}).get("frames", [])
        if not frames:
            self._transitional = False
            if on_finished:
                on_finished()
            return
        self._animation_name = animation_name
        self._frames = frames
        self._frame_index = 0
        self._loop = False
        self._once_callback = on_finished
        self._show_current_frame()

    def _pick_animation(self, status: str, candidates: list[str]) -> str:
        # sorteia entre as candidatas do status, evitando repetir a mesma
        # da última vez (quando há mais de uma opção) — dá variedade de
        # animação e, de graça, de som (cada animação tem seus próprios sons).
        if len(candidates) == 1:
            return candidates[0]
        previous = self._last_animation_by_status.get(status)
        options = [c for c in candidates if c != previous] or candidates
        choice = random.choice(options)
        self._last_animation_by_status[status] = choice
        return choice

    def _advance_frame(self) -> None:
        if not self._frames:
            return
        if self._frame_index + 1 >= len(self._frames):
            if self._loop:
                self._on_loop_restart()
            else:
                callback = self._once_callback
                self._once_callback = None
                if callback:
                    callback()
            return
        self._frame_index += 1
        self._show_current_frame()

    def _on_loop_restart(self) -> None:
        # se a animação atual é a "certa" pra atividade real (ex.: ainda
        # rodando Bash), continua nela — repetir faz sentido, ela ainda
        # reflete o que está acontecendo. Sem atividade conhecida, sorteia
        # de novo a cada volta pra não ficar preso na mesma sequência/som
        # por um status "working" que dura muito tempo.
        preferred = ACTIVITY_ANIMATION.get(self._activity)
        if not (preferred and preferred == self._animation_name):
            status_animations = self._data["status_animations"]
            candidates = status_animations.get(self._status) or status_animations[DEFAULT_STATUS_ANIMATION]
            self._animation_name = self._pick_animation(self._status, candidates)
            self._frames = self._data["animations"][self._animation_name]["frames"]
        self._frame_index = 0
        self._show_current_frame()

    def _show_current_frame(self) -> None:
        if not self._frames:
            return
        frame = self._frames[self._frame_index]
        duration = frame["duration"]
        if self._transitional:
            # alguns personagens (ex.: F1, Rocky) trazem Show/Hide com frames
            # de 10ms no asset original — imperceptível como transição de
            # entrada/saída, então garantimos um mínimo visível só aqui.
            duration = max(duration, MIN_TRANSITION_FRAME_MS)
        self._timer.start(duration)
        sound_id = frame.get("sound")
        # isVisible() já considera a janela do painel estar oculta (não só
        # este widget) — sem plateia, sem som. O cooldown evita o mesmo som
        # martelando toda hora (algumas animações repetem o mesmo id várias
        # vezes numa única passada, e loops longos repetiriam de novo a cada volta).
        if self._sound_enabled and sound_id and self.isVisible() and self._sound_ready(sound_id):
            play_sound(_sound_path(self._agent_name, sound_id))
            self._sound_last_played[sound_id] = time.monotonic()
        self.update()

    def _sound_ready(self, sound_id: str) -> bool:
        last = self._sound_last_played.get(sound_id)
        return last is None or (time.monotonic() - last) >= SOUND_COOLDOWN_SECONDS

    def paintEvent(self, _event) -> None:
        if not self._frames:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        x, y = self._frames[self._frame_index]["images"][0]
        source = QRectF(x, y, self._frame_width, self._frame_height)
        painter.drawPixmap(QRectF(self.rect()), self._pixmap, source)
        painter.end()
