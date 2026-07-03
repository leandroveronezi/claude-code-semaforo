"""Personagem animado (estilo MS Agent/Clippy) por sessão, sincronizado com o status.

Os assets em assets/mascot/<Nome>/ vêm do projeto clippy.js
(github.com/clippyjs/clippy.js): map.png é a planilha de sprites original e
agent.json é uma cópia fiel do agent.js de lá (ver scripts/import_mascot_agents.py),
incluindo o "branching" (variação probabilística entre frames), "exitBranch"
(onde a animação corta caminho quando pedimos pra ela se encerrar) e frames
com múltiplas imagens sobrepostas — nem todo personagem tem os mesmos nomes
de animação, ex.: o Rover usa "Idle"/"Thinking"/"GetAttention" em vez de
"Idle1_1"/"Processing"/"Alert". Ver README do clippy.js pra detalhes/licença.

O motor de reprodução (mostrar/avançar frame) é um port direto do
clippy.js/src/animator.js original: sem isso, animações de idle teriam que
ser achatadas numa sequência linear (perdendo toda a variação de
"branching") e frames de puro controle de fluxo (sem imagem) quebrariam o
desenho — foi exatamente esse achatamento que a importação antiga fazia.
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
RELIEF_ANIMATION = "Congratulate"  # gesto de alívio/comemoração ao sair de erro pra idle
# gesto discreto ao terminar de trabalhar sem erro nenhum (working -> idle) —
# mais sutil que o RELIEF_ANIMATION, pra não repetir a mesma festa toda vez
# que uma sessão termina; sorteado entre o que o personagem tiver disponível.
SUCCESS_EXTRA_NAMES = ("CharacterSucceeds", "Pleased", "Acknowledge", "Wave")
# nomes alternativos de entrada/saída: sorteados junto com Show/Hide quando o
# personagem os tiver (ex.: Genius/F1/Clippy/Links/Rocky têm uma "Goodbye"
# com o personagem andando até uma porta, bem mais expressiva que o Hide
# genérico de encolher e sumir).
ENTRANCE_EXTRA_NAMES = ("Greeting", "Greet")
EXIT_EXTRA_NAMES = ("Goodbye", "GoodBye")
# rede de segurança: algumas animações usam "useExitBranching" (ficam
# tocando em loop esperando um pedido de saída) — se por algum motivo uma
# entrada/saída/alívio nunca receber esse pedido, isso evita ficar preso
# nela pra sempre.
EXIT_SAFETY_TIMEOUT_MS = 8000
# 2ª rede: o pedido de saída só funciona se o frame onde a animação congelou
# tiver um "exitBranch" definido — nem sempre tem, dependendo de qual
# caminho aleatório o branching seguiu até congelar. Se isso não resolver
# rápido, força o corte.
HARD_SAFETY_TIMEOUT_MS = 2000

# atividade (vinda do tool_name real, via hooks/status_hook.py) -> animação
# preferida, quando o personagem tiver essa animação pro status atual. Sem
# atividade reconhecida, cai no sorteio entre as candidatas do status.
ACTIVITY_ANIMATION = {
    "thinking": "Thinking",
    "writing": "Writing",
    "searching": "Searching",
    "processing": "Processing",
    "reading": "Reading",
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
        self._data: dict = {}
        self._last_animation_by_status: dict[str, str] = {}
        self._sound_last_played: dict[str, float] = {}

        # motor de frames (port de clippy.js/src/animator.js)
        self._current_animation: dict | None = None
        self._current_animation_name: str | None = None
        self._current_frame_index = 0
        self._current_frame: dict | None = None
        self._exiting = False
        self._end_callback: Callable[[str, bool], None] | None = None
        self._started = False

        # tocando Show/Hide/Congratulate (entrada/saída/alívio) —
        # play_status() não deve interromper, só guarda o status/atividade
        # pendente pra aplicar assim que a transição acabar
        self._transitional = False
        self._pending_status: str | None = None
        self._pending_activity: str | None = None

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._step)

        self._safety_timer = QTimer(self)
        self._safety_timer.setSingleShot(True)
        self._safety_timer.timeout.connect(self._on_safety_timeout)

        # 2ª rede: pedir saída (_exit_animation) só funciona se o frame onde
        # a animação congelou tiver um "exitBranch" — depende de por qual
        # caminho aleatório o branching passou até congelar, então nem
        # sempre tem um definido. Se a saída graciosa não resolver rápido,
        # força o corte pra nunca travar o mascote pra sempre.
        self._hard_safety_timer = QTimer(self)
        self._hard_safety_timer.setSingleShot(True)
        self._hard_safety_timer.timeout.connect(self._on_hard_safety_timeout)

        self.set_agent(agent_name)

    def set_agent(self, name: str) -> None:
        if name == self._agent_name:
            return
        self._agent_name = name
        self._data = _load_agent_data(name)
        self._pixmap = _load_pixmap(name)
        self._frame_width, self._frame_height = self._data["framesize"]
        self._current_animation = None
        self._current_animation_name = None
        self._current_frame = None
        self._transitional = False
        self.play_status(self._status, self._activity)

    def set_sound_enabled(self, enabled: bool) -> None:
        self._sound_enabled = enabled

    # -- API de alto nível (status/entrada/saída/alívio) ---------------------------

    def play_status(self, status: str, activity: str | None = None) -> None:
        if self._transitional:
            self._pending_status = status
            self._pending_activity = activity
            return
        same_target = status == self._status and activity == self._activity
        self._status = status
        self._activity = activity
        if self._current_animation_name is None:
            self._settle_into_status()
        elif not same_target:
            # não troca o frame na hora: pede uma saída graciosa (via
            # exitBranch, se a animação atual tiver um por perto) e deixa
            # _on_status_end assentar no novo alvo quando ela concluir
            self._exit_animation()
        # same_target e já tocando algo: o loop atual se renova sozinho
        # (_on_status_end chama _settle_into_status de novo a cada EXITED)

    def play_intro(self, on_finished: Callable[[], None] | None = None) -> None:
        name = self._pick_transition_animation("Show", ENTRANCE_EXTRA_NAMES)
        self._play_transitional(name, on_finished, resume=True)

    def play_relief(
        self, status: str, activity: str | None = None, on_finished: Callable[[], None] | None = None
    ) -> None:
        """Gesto rápido de alívio/comemoração (ex.: saindo de erro pra idle)
        antes de assentar no status normal informado."""
        self._pending_status = status
        self._pending_activity = activity
        self._play_transitional(RELIEF_ANIMATION, on_finished, resume=True)

    def play_success(
        self, status: str, activity: str | None = None, on_finished: Callable[[], None] | None = None
    ) -> None:
        """Gesto discreto de 'terminei numa boa' (ex.: saindo de working pra
        idle sem ter passado por erro) antes de assentar no status normal
        informado — sorteia entre o que o personagem tiver de
        SUCCESS_EXTRA_NAMES; se não tiver nenhum, só aplica o status direto."""
        name = self._pick_available(SUCCESS_EXTRA_NAMES)
        if name is None:
            self.play_status(status, activity)
            if on_finished:
                on_finished()
            return
        self._pending_status = status
        self._pending_activity = activity
        self._play_transitional(name, on_finished, resume=True)

    def _pick_available(self, names: tuple[str, ...]) -> str | None:
        available = [n for n in names if n in self._data["animations"]]
        return random.choice(available) if available else None

    def play_outro(self, on_finished: Callable[[], None]) -> None:
        name = self._pick_transition_animation("Hide", EXIT_EXTRA_NAMES)
        self._play_transitional(name, on_finished, resume=False)

    def play_glance(self, direction: str, on_finished: Callable[[], None] | None = None) -> None:
        """Dá uma olhada rápida na direção onde o mouse está (Up/Down/Left/
        Right) e volta pro status normal em seguida — usado quando o cursor
        se aproxima do mascote, no lugar do clique que o clippy.js original
        usava pra decidir a direção. Não faz nada se o personagem não tiver
        gesto pra essa direção, ou se já estiver no meio de outra transição."""
        if self._transitional:
            return
        name = self._glance_animation_for(direction)
        if name is None:
            return
        self._play_transitional(name, on_finished, resume=True)

    def _glance_animation_for(self, direction: str) -> str | None:
        for prefix in ("Gesture", "Look"):
            name = f"{prefix}{direction}"
            if name in self._data["animations"]:
                return name
        return None

    def _pick_transition_animation(self, base: str, extra_names: tuple[str, ...]) -> str:
        candidates = [base] + [n for n in extra_names if n in self._data["animations"]]
        return random.choice(candidates)

    def _play_transitional(
        self, name: str, on_finished: Callable[[], None] | None, resume: bool
    ) -> None:
        self._transitional = True

        def _finish(_name: str, exited: bool) -> None:
            if not exited:
                return  # WAITING: ainda tocando, só EXITED encerra de fato
            self._safety_timer.stop()
            self._hard_safety_timer.stop()
            self._transitional = False
            if resume:
                status = self._pending_status if self._pending_status is not None else self._status
                activity = self._pending_activity
                self._pending_status = None
                self._pending_activity = None
                self._status = status
                self._activity = activity
                self._settle_into_status()
            if on_finished:
                on_finished()

        self._show_animation(name, _finish)
        self._safety_timer.start(EXIT_SAFETY_TIMEOUT_MS)

    def _on_safety_timeout(self) -> None:
        if self._transitional:
            self._exit_animation()
            self._hard_safety_timer.start(HARD_SAFETY_TIMEOUT_MS)

    def _on_hard_safety_timeout(self) -> None:
        # pediu saída e mesmo assim não resolveu (congelou num frame sem
        # exitBranch) — força o fim pra não travar o mascote pra sempre.
        if self._transitional and self._end_callback:
            callback = self._end_callback
            name = self._current_animation_name
            callback(name, True)

    def _settle_into_status(self) -> None:
        status_animations = self._data["status_animations"]
        candidates = status_animations.get(self._status) or status_animations[DEFAULT_STATUS_ANIMATION]
        name = self._resolve_animation(self._status, self._activity, candidates)
        self._show_animation(name, self._on_status_end)

    def _on_status_end(self, _name: str, exited: bool) -> None:
        if not exited:
            return  # WAITING: motor já está de bem com a vida, tocando em loop
        self._settle_into_status()  # reassenta no alvo atual (pode ter mudado nesse meio-tempo)

    def _resolve_animation(self, status: str, activity: str | None, candidates: list[str]) -> str:
        preferred = ACTIVITY_ANIMATION.get(activity)
        if preferred and preferred in candidates:
            return preferred
        return self._pick_animation(status, candidates)

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

    # -- motor de frames (port de clippy.js/src/animator.js) -----------------------

    def _show_animation(self, name: str, end_callback: Callable[[str, bool], None]) -> None:
        self._exiting = False
        animation = self._data["animations"].get(name)
        if animation is None:
            end_callback(name, True)
            return
        self._current_animation = animation
        self._current_animation_name = name
        self._current_frame_index = 0
        self._current_frame = None
        self._end_callback = end_callback
        if not self._started:
            self._started = True
            self._step()

    def _exit_animation(self) -> None:
        self._exiting = True

    def _get_next_frame_index(self) -> int:
        if self._current_frame is None:
            return 0
        frame = self._current_frame
        if self._exiting and "exitBranch" in frame:
            return frame["exitBranch"]
        branching = frame.get("branching")
        if branching:
            roll = random.random() * 100
            for branch in branching["branches"]:
                weight = branch["weight"]
                if roll <= weight:
                    return branch["frameIndex"]
                roll -= weight
        return self._current_frame_index + 1

    def _at_last_frame(self) -> bool:
        frames = self._current_animation["frames"]
        return self._current_frame_index >= len(frames) - 1

    def _step(self) -> None:
        if self._current_animation is None:
            return
        frames = self._current_animation["frames"]
        new_index = min(self._get_next_frame_index(), len(frames) - 1)
        frame_changed = self._current_frame is None or self._current_frame_index != new_index
        self._current_frame_index = new_index

        use_exit_branching = self._current_animation.get("useExitBranching", False)
        # sempre troca o frame, a menos que já estejamos no último frame de
        # uma animação com useExitBranching — aí ela "congela" no frame de
        # espera (repetindo o mesmo branching) até alguém pedir saída.
        if not (self._at_last_frame() and use_exit_branching):
            self._current_frame = frames[self._current_frame_index]

        self._draw_current_frame()

        duration = self._current_frame.get("duration", 0)
        if self._transitional:
            # alguns personagens (ex.: F1, Rocky) trazem Show/Hide com frames
            # de 10ms no asset original — imperceptível como transição de
            # entrada/saída, então garantimos um mínimo visível só aqui.
            duration = max(duration, MIN_TRANSITION_FRAME_MS)
        self._timer.start(duration)

        if self._end_callback and frame_changed and self._at_last_frame():
            callback = self._end_callback
            name = self._current_animation_name
            exited = not (use_exit_branching and not self._exiting)
            callback(name, exited)

    def _draw_current_frame(self) -> None:
        frame = self._current_frame
        sound_id = frame.get("sound") if frame else None
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
        frame = self._current_frame
        if not frame:
            return
        images = frame.get("images") or []
        if not images:
            return  # frame de puro controle (branching) — sem imagem, fica em branco
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        target = QRectF(self.rect())
        for x, y in images:
            source = QRectF(x, y, self._frame_width, self._frame_height)
            painter.drawPixmap(target, self._pixmap, source)
        painter.end()
