"""Descobre sessões monitoradas (um arquivo de status = um editor/aba) e
mantém o painel único de semáforos e o ícone de bandeja sincronizados com elas."""
import shutil
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path

from PyQt6.QtCore import QFileSystemWatcher, QPoint, QSettings, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QGuiApplication, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from account_usage import fetch_account_usage, load_cached_usage, parse_reset_datetime, save_cached_usage
from audio import play_sound
from config import (
    Config,
    DEFAULT_SESSION_PCT_ALERT_MESSAGE,
    DEFAULT_TOKEN_ALERT_MESSAGE,
    DEFAULT_WEEK_PCT_ALERT_MESSAGE,
)
from foreground import active_window_pid
from light_column import LIGHT_COLORS
from mascot_overlay import MascotOverlay
from semaphore_panel import SemaphorePanel
from settings_dialog import SettingsDialog
from status_store import read_status, remove_status, sessions_dir, write_status

ALERT_SOUND = Path(__file__).resolve().parent / "assets" / "alert.wav"
ALERT_VOLUME_ARGS = {
    "paplay": ["--volume=98304"],  # 65536 = 100%; 98304 = 150%
    "pw-play": ["--volume=1.5"],
}
FALLBACK_POLL_MS = 2000  # rede de segurança, caso o watcher perca algum evento
STALE_CHECK_MS = 30_000
STALE_ACTIVE_SECONDS = 10 * 60  # working/error parado há mais que isso -> provável sessão travada, volta a idle
STALE_REMOVE_SECONDS = 4 * 60 * 60  # qualquer status parado há mais que isso -> sessão abandonada, remove
STATUS_PRIORITY = ("error", "working", "idle")  # pior -> melhor, para o ícone agregado
SETTINGS_KEY = "panel/pos"
ACCOUNT_USAGE_POLL_MS = 5 * 60 * 1000  # rede de segurança pra quando não há Stop nenhum (usuário parado/AFK); o gatilho principal é _on_session_finished
ACCOUNT_USAGE_FIRST_FETCH_MS = 5_000
ACCOUNT_USAGE_MIN_INTERVAL_SECONDS = 60  # debounce do gatilho por Stop: várias sessões terminando quase juntas não devem virar N consultas (fetch_account_usage() é lento, ~15s, spawna um claude de verdade, e a Anthropic parece limitar consultas em sequência rápida — ver account_usage.py)
RESET_REQUERY_BUFFER_SECONDS = 30  # folga depois do horário de reset (best-effort: dá tempo do servidor rolar a janela antes de consultarmos)
RESET_REQUERY_MAX_DELAY_SECONDS = 8 * 24 * 60 * 60  # teto de sanidade (semana nunca reseta a mais de 7 dias daqui) — protege contra um parse de data estranho agendar pra um delay absurdo


class _AccountUsageThread(QThread):
    """Roda fetch_account_usage() (bloqueante, ~15s) fora da thread da UI.

    run() é sobrescrito diretamente em vez do padrão moveToThread()+started/quit():
    esse padrão tem uma corrida conhecida do Qt quando o trabalho conectado a
    started() é rápido/direto o bastante — o quit() (emitido cross-thread por
    finished, portanto enfileirado) pode chegar antes do exec() da thread nem
    ter começado, vira um no-op, e a thread fica presa num loop de eventos vazio
    pra sempre (isRunning() nunca volta a False). Quando o Python por fim coleta
    o QThread órfão (refcount chega a zero), o destructor do Qt aborta o
    processo com "QThread: Destroyed while thread is still running" — foi
    exatamente esse crash, reproduzido de forma 100% determinística (a cada
    fetch bem-sucedido, ~1s depois), que motivou essa reescrita. Sobrescrever
    run() evita o problema inteiro: quando run() retorna, a thread já está
    oficialmente terminada, sem precisar de quit()/exec() nenhum."""

    finished_with_data = pyqtSignal(object)

    def run(self) -> None:
        try:
            data = fetch_account_usage()
        except Exception:
            data = None
        self.finished_with_data.emit(data)


class SessionManager:
    def __init__(self, panel: SemaphorePanel, directory: Path | None = None):
        self.panel = panel
        self.directory = directory or sessions_dir()
        self._updated_at: dict[str, float] = {}
        self._statuses: dict[str, str] = {}
        self._labels: dict[str, str] = {}
        self._messages: dict[str, str | None] = {}
        self._activities: dict[str, str | None] = {}
        self._pid_chains: dict[str, list[int]] = {}
        self._usages: dict[str, dict | None] = {}
        self._status_since: dict[str, float] = {}  # quando o status atual começou (ordem de chegada p/ mascote)
        self._alerted_tokens: dict[str, set[int]] = {}  # limiares de contexto já disparados por sessão (ver _check_token_alerts)
        self._alerted_session_pct: set[int] = set()  # limiares de % de cota (sessão 5h) já disparados (ver _check_account_usage_alerts)
        self._alerted_week_pct: set[int] = set()  # limiares de % de cota (semana 7d) já disparados (ver _check_account_usage_alerts)
        self._manually_hidden = False  # usuário escondeu o painel enquanto havia sessões
        self.config = Config.load()
        self.panel.set_usage_config(self.config.usage_bar_enabled, self.config.usage_thresholds)
        self.mascot_overlay = MascotOverlay(self.config)
        self._settings_dialog: SettingsDialog | None = None
        self.settings = QSettings("SemaforoStatus", "Posicoes")

        saved_pos = self.settings.value(SETTINGS_KEY)
        if isinstance(saved_pos, QPoint):
            self.panel.move(self._clamp_to_screen(saved_pos))
        self.panel.moved.connect(lambda pos: self.settings.setValue(SETTINGS_KEY, pos))
        self.panel.right_clicked.connect(self._toggle_panel)

        # mesmo cuidado do MascotOverlay: o clamp acima só protege a posição
        # salva ao abrir; dock/undock costuma reposicionar uma tela que já
        # existia (sem screenAdded/screenRemoved), então também escutamos
        # mudança de geometria pra reancorar o painel em tempo real.
        app = QGuiApplication.instance()
        app.aboutToQuit.connect(self._wait_for_account_usage_thread)
        app.screenAdded.connect(self._on_screen_added)
        app.screenRemoved.connect(self._on_screens_changed)
        app.primaryScreenChanged.connect(self._on_screens_changed)
        for screen in app.screens():
            self._watch_screen(screen)

        # QFileSystemWatcher dá atualização instantânea; o timer abaixo é só
        # um plano B, pois escritas atômicas (os.replace) às vezes derrubam o watch.
        self.watcher = QFileSystemWatcher()
        self.watcher.directoryChanged.connect(self._scan)
        self.watcher.fileChanged.connect(self._scan)

        self.fallback_timer = QTimer()
        self.fallback_timer.setInterval(FALLBACK_POLL_MS)
        self.fallback_timer.timeout.connect(self._scan)

        self.stale_timer = QTimer()
        self.stale_timer.setInterval(STALE_CHECK_MS)
        self.stale_timer.timeout.connect(self._check_stale)

        # cache em disco (ver account_usage.load_cached_usage): mostra o
        # último valor conhecido de imediato, em vez da caixa ficar sumida
        # até a primeira consulta real (lenta, ~5-30s) responder.
        self._account_usage: dict | None = load_cached_usage()
        self._account_usage_thread: _AccountUsageThread | None = None
        self._account_usage_last_attempt = 0.0
        self.account_usage_timer = QTimer()
        self.account_usage_timer.setInterval(ACCOUNT_USAGE_POLL_MS)
        self.account_usage_timer.timeout.connect(self._poll_account_usage)

        # agendamento único (não repetitivo): quando sessão ou semana bate
        # 100%, os gatilhos normais (Stop, timer de 5min) já não bastam —
        # com a cota estourada o usuário pode nem conseguir gerar novos
        # Stops — então programamos uma consulta extra pra logo depois do
        # horário de reset conhecido em vez de esperar o próximo tick.
        self.reset_requery_timer = QTimer()
        self.reset_requery_timer.setSingleShot(True)
        self.reset_requery_timer.timeout.connect(self._poll_account_usage)

        self.tray = QSystemTrayIcon()
        self.tray.setToolTip("Semáforo de Status")
        self.menu = QMenu()
        self.tray.setContextMenu(self.menu)
        self.menu.aboutToShow.connect(self._rebuild_menu)
        self.tray.activated.connect(self._on_tray_activated)

        self._update_tray_icon("idle")
        self.tray.show()
        self._update_account_usage_badge()
        self._update_tray_tooltip()

    def start(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        self.watcher.addPath(str(self.directory))
        self._scan()
        self.fallback_timer.start()
        self.stale_timer.start()
        self.account_usage_timer.start()
        QTimer.singleShot(ACCOUNT_USAGE_FIRST_FETCH_MS, self._poll_account_usage)

    @staticmethod
    def _clamp_to_screen(point: QPoint) -> QPoint:
        """Evita restaurar o painel numa posição que ficou fora de qualquer
        monitor conectado (ex.: troca do monitor externo por um com outra
        resolução/arranjo). Ver mesma lógica em MascotOverlay._clamp_to_screen."""
        screen = QGuiApplication.screenAt(point) or QGuiApplication.primaryScreen()
        if screen is None:
            return point
        bounds = screen.availableGeometry()
        x = min(max(point.x(), bounds.left()), bounds.right())
        y = min(max(point.y(), bounds.top()), bounds.bottom())
        return QPoint(x, y)

    def _watch_screen(self, screen) -> None:
        screen.geometryChanged.connect(self._on_screens_changed)
        screen.availableGeometryChanged.connect(self._on_screens_changed)

    def _on_screen_added(self, screen) -> None:
        self._watch_screen(screen)
        self._on_screens_changed()

    def _on_screens_changed(self, _screen=None) -> None:
        """Monitor conectado/desconectado/reposicionado com o app já
        rodando: reancora o painel se ele ficou fora de qualquer tela
        visível."""
        pos = self.panel.pos()
        clamped = self._clamp_to_screen(pos)
        if clamped != pos:
            self.panel.move(clamped)
            self.settings.setValue(SETTINGS_KEY, clamped)

    # -- descoberta de sessões -------------------------------------------------
    def _scan(self, *_args) -> None:
        # usamos o "updated_at" gravado dentro do próprio JSON (alta precisão,
        # via time.time()) em vez do mtime do arquivo: em algumas escritas
        # rápidas em sequência o mtime do filesystem não muda, e ficaríamos
        # sem notar a atualização.
        seen = set()
        paths = list(self.directory.glob("*.json")) if self.directory.exists() else []
        for path in paths:
            session_id = path.stem
            seen.add(session_id)
            data = read_status(path)
            if data is None:
                continue
            updated_at = data.get("updated_at")
            if updated_at is not None and self._updated_at.get(session_id) == updated_at:
                continue
            self._updated_at[session_id] = updated_at
            label = data.get("label", session_id)
            status = data.get("status", "idle")
            message = data.get("message")
            activity = data.get("activity")
            previous_status = self._statuses.get(session_id)
            self._labels[session_id] = label
            self._statuses[session_id] = status
            self._messages[session_id] = message
            self._activities[session_id] = activity
            self._pid_chains[session_id] = data.get("pid_chain") or []
            self._usages[session_id] = data.get("usage")
            total_tokens = (data.get("usage") or {}).get("total_tokens")
            if total_tokens is not None:
                self._check_token_alerts(session_id, label, total_tokens)
            if status != previous_status:
                self._status_since[session_id] = time.time()
                # "chegou" numa sessão ociosa vindo de outro estado -> notificação
                # passageira na fila do mascote; sessão nova descoberta já ociosa
                # (previous_status is None) não conta como chegada.
                if status == "idle" and previous_status is not None:
                    self.mascot_overlay.enqueue_idle(label, message)
                    if previous_status == "working":
                        # turno acabou de verdade (hook Stop) -> boa hora pra
                        # atualizar a cota; debounce em _poll_account_usage
                        # evita N consultas quando várias sessões terminam juntas.
                        self._poll_account_usage()
            self.panel.upsert_session(session_id, label, status, message, data.get("usage"))
            if status == "error" and previous_status != "error":
                if not self._session_in_foreground(session_id):
                    self._play_alert_sound()
                    self._notify_desktop(label)

        for session_id in list(self._updated_at):
            if session_id not in seen:
                del self._updated_at[session_id]
                self._statuses.pop(session_id, None)
                self._labels.pop(session_id, None)
                self._messages.pop(session_id, None)
                self._activities.pop(session_id, None)
                self._pid_chains.pop(session_id, None)
                self._usages.pop(session_id, None)
                self._status_since.pop(session_id, None)
                self._alerted_tokens.pop(session_id, None)
                self.panel.remove_session(session_id)

        self._update_tray_icon(self._aggregate_status())
        self._update_mascot()
        self._sync_panel_visibility()
        self._resync_watched_files(paths)

    def _session_in_foreground(self, session_id: str) -> bool:
        """True só quando temos certeza de que a janela ativa pertence a essa
        sessão (algum ancestral do processo que gravou o status é o dono da
        janela em foco). Qualquer incerteza (Wayland, xprop ausente,
        pid_chain vazia) volta False, pra não deixar de alertar por engano."""
        pid_chain = self._pid_chains.get(session_id)
        if not pid_chain:
            return False
        active_pid = active_window_pid()
        if active_pid is None:
            return False
        return active_pid in pid_chain

    def _play_alert_sound(self) -> None:
        if self.config.alert_beep_enabled:
            play_sound(ALERT_SOUND, ALERT_VOLUME_ARGS)

    def _notify_desktop(self, label: str, message: str = "Precisa da sua atenção", icon: str = "dialog-warning") -> None:
        if not self.config.notification_enabled:
            return
        if not shutil.which("notify-send"):
            return
        try:
            subprocess.Popen(
                ["notify-send", "-a", "Semáforo de Status", "-i", icon, label, message],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            pass

    def _check_token_alerts(self, session_id: str, label: str, total_tokens: int) -> None:
        """Dispara um aviso (balão do mascote + notificação) uma única vez por
        limiar configurado, ao atingir `tokens`. Histerese: só rearma depois que
        `total_tokens` cai abaixo de `tokens - token_alert_reset_margin` — sem
        isso, ficaríamos alertando toda hora perto do limiar. Não injeta nem
        dispara `/compact` sozinho: a extensão do VSCode descarta silenciosamente
        um prompt mandado de fora quando a sessão já está com o painel aberto,
        então isso é só um lembrete pro usuário compactar manualmente."""
        fired = self._alerted_tokens.setdefault(session_id, set())
        margin = self.config.token_alert_reset_margin
        for tokens, message, enabled in self.config.token_alert_thresholds:
            if not enabled:
                continue
            if total_tokens >= tokens:
                if tokens not in fired:
                    fired.add(tokens)
                    text = self._format_token_alert(message, total_tokens, label, tokens)
                    self.mascot_overlay.enqueue_idle(label, text)
                    if not self._session_in_foreground(session_id):
                        self._notify_desktop(label, text, icon="dialog-information")
            elif total_tokens < tokens - margin:
                fired.discard(tokens)

    def _format_token_alert(self, message: str, total_tokens: int, label: str, threshold: int) -> str:
        """Aplica o texto do próprio limiar (`message`). Como o texto é livre pra
        edição, um placeholder digitado errado (ex.: {toekns}) não pode derrubar
        o app — cai pro texto padrão embutido nesse caso."""
        values = {
            "tokens": f"{total_tokens:,}".replace(",", "."),
            "session": label,
            "threshold": f"{threshold:,}".replace(",", "."),
        }
        try:
            return message.format(**values)
        except (KeyError, IndexError, ValueError):
            return DEFAULT_TOKEN_ALERT_MESSAGE.format(**values)

    def _check_stale(self) -> None:
        now = time.time()
        for session_id, updated_at in list(self._updated_at.items()):
            age = now - updated_at
            status = self._statuses.get(session_id, "idle")

            if age > STALE_REMOVE_SECONDS:
                remove_status(session_id, self.directory)
            elif age > STALE_ACTIVE_SECONDS and status != "idle":
                write_status(session_id, "idle", self._labels.get(session_id, session_id), self.directory)

        self._scan()

    def _resync_watched_files(self, paths: list[Path]) -> None:
        # cada gravação usa os.replace (troca de inode), o que derruba o watch
        # do arquivo antigo silenciosamente — reobservamos tudo a cada scan.
        watched_files = self.watcher.files()
        if watched_files:
            self.watcher.removePaths(watched_files)
        new_paths = [str(p) for p in paths]
        if new_paths:
            self.watcher.addPaths(new_paths)

    # -- cota da conta (Session 5h / Weekly 7d, via /usage) ------------------
    def _wait_for_account_usage_thread(self) -> None:
        """Sem isso, fechar o app (menu Sair) com uma consulta de cota em
        andamento (fetch_account_usage é bloqueante, até ~15s) deixaria o
        QThread órfão no meio do trabalho quando o processo termina — espera
        terminar (no pior caso, alguns segundos de atraso pra fechar) em vez
        de deixar isso acontecer. Só wait(): _AccountUsageThread sobrescreve
        run() em vez de usar exec(), então não há loop de eventos pra quit()
        sinalizar (ver comentário da classe)."""
        if self._account_usage_thread is not None:
            self._account_usage_thread.wait()

    def _poll_account_usage(self) -> None:
        if self._account_usage_thread is not None:
            return  # já tem uma consulta em andamento, não sobrepõe
        since_last = time.time() - self._account_usage_last_attempt
        if since_last < ACCOUNT_USAGE_MIN_INTERVAL_SECONDS:
            return  # debounce do gatilho por Stop (ver ACCOUNT_USAGE_MIN_INTERVAL_SECONDS)
        self._account_usage_last_attempt = time.time()
        thread = _AccountUsageThread()
        thread.finished_with_data.connect(self._on_account_usage)
        thread.finished.connect(self._on_account_usage_thread_finished)
        self._account_usage_thread = thread
        thread.start()

    def _on_account_usage(self, data: dict | None) -> None:
        """Mescla em vez de substituir: a consulta da sessão (5h) sofre
        throttling do lado da Anthropic com mais frequência que a da semana
        (ver account_usage.py), então uma consulta parcial não deve apagar o
        último valor de sessão que já tínhamos conseguido.

        Importante: NÃO derruba `self._account_usage_thread` aqui. `finished_with_data`
        é emitido de dentro de run(), antes dele retornar — como é uma conexão
        enfileirada, esse handler pode rodar na thread principal enquanto a
        worker thread ainda está terminando de retornar de run(). Se essa fosse
        a última referência Python ao QThread, ele seria desalocado (destructor
        do Qt chamado) com `running` ainda True, reproduzindo "QThread: Destroyed
        while thread is still running". `_on_account_usage_thread_finished`
        (conectado a `finished`, que só dispara depois que run() já retornou
        de verdade) é o único lugar seguro pra isso — ver comentário lá."""
        if data:
            self._account_usage = {**(self._account_usage or {}), **data}
            save_cached_usage(self._account_usage)
            self._schedule_reset_requery()
            self._check_account_usage_alerts()
        self._update_tray_tooltip()
        self._update_account_usage_badge()

    def _check_account_usage_alerts(self) -> None:
        """Mesma mecânica de `_check_token_alerts`, mas pro % de cota da conta
        (sessão 5h / semana 7d) em vez de tokens acumulados. Diferente dos
        avisos de contexto, não é por sessão monitorada — é um só estado por
        conta, então não há supressão por foreground: o usuário pode estar
        de olho em qualquer sessão (ou em nenhuma) quando a cota estoura."""
        usage = self._account_usage or {}
        self._check_pct_alerts(
            usage.get("session_pct"), usage.get("session_resets"),
            self.config.session_pct_alert_thresholds, self.config.session_pct_alert_reset_margin,
            self._alerted_session_pct, DEFAULT_SESSION_PCT_ALERT_MESSAGE,
        )
        self._check_pct_alerts(
            usage.get("week_pct"), usage.get("week_resets"),
            self.config.week_pct_alert_thresholds, self.config.week_pct_alert_reset_margin,
            self._alerted_week_pct, DEFAULT_WEEK_PCT_ALERT_MESSAGE,
        )

    def _check_pct_alerts(
        self, current_pct, resets_at, thresholds: list, margin: int, fired: set[int], default_message: str,
    ) -> None:
        if current_pct is None:
            return
        for pct, message, enabled in thresholds:
            if not enabled:
                continue
            if current_pct >= pct:
                if pct not in fired:
                    fired.add(pct)
                    text = self._format_pct_alert(message, current_pct, resets_at, pct, default_message)
                    self.mascot_overlay.enqueue_idle("Cota da conta", text)
                    self._notify_desktop("Cota da conta", text, icon="dialog-information")
            elif current_pct < pct - margin:
                fired.discard(pct)

    def _format_pct_alert(self, message: str, current_pct, resets_at, threshold: int, default_message: str) -> str:
        """Mesma rede de segurança de `_format_token_alert`: um placeholder
        digitado errado no texto (livre pra edição) cai pro texto padrão
        embutido em vez de derrubar o app."""
        values = {"pct": current_pct, "reset": resets_at or "?", "threshold": threshold}
        try:
            return message.format(**values)
        except (KeyError, IndexError, ValueError):
            return default_message.format(**values)

    def _schedule_reset_requery(self) -> None:
        """Se sessão e/ou semana estiverem em 100%, agenda uma consulta
        única pra pouco depois do horário de reset mais próximo entre as que
        estiverem no limite — ver comentário de reset_requery_timer."""
        usage = self._account_usage or {}
        targets = []
        for pct_key, resets_key in (("session_pct", "session_resets"), ("week_pct", "week_resets")):
            if (usage.get(pct_key) or 0) < 100:
                continue
            reset_at = parse_reset_datetime(usage.get(resets_key) or "")
            if reset_at is not None:
                targets.append(reset_at)
        if not targets:
            return
        target = min(targets) + timedelta(seconds=RESET_REQUERY_BUFFER_SECONDS)
        delay_seconds = (target - datetime.now(target.tzinfo)).total_seconds()
        if 0 < delay_seconds <= RESET_REQUERY_MAX_DELAY_SECONDS:
            self.reset_requery_timer.start(int(delay_seconds * 1000))

    def _on_account_usage_thread_finished(self) -> None:
        """`finished` só é emitido depois que run() já retornou de fato (a
        flag `running` do QThread já está False nesse ponto) — diferente de
        `finished_with_data`, que é emitido de dentro de run() e pode ser
        processado enquanto ele ainda está retornando. Por isso a última
        referência Python só é derrubada aqui, nunca em `_on_account_usage`."""
        thread = self._account_usage_thread
        self._account_usage_thread = None
        if thread is not None:
            thread.deleteLater()

    def _update_account_usage_badge(self) -> None:
        data = self._account_usage if self.config.account_usage_badge_enabled else None
        self.mascot_overlay.set_account_usage(data)
        self._sync_mascot_visibility()

    def _update_tray_tooltip(self) -> None:
        lines = ["Semáforo de Status"]
        usage = self._account_usage or {}
        session_pct = usage.get("session_pct")
        week_pct = usage.get("week_pct")
        if session_pct is not None:
            lines.append(f"Sessão (5h): {session_pct}% · reseta {usage.get('session_resets', '?')}")
        if week_pct is not None:
            lines.append(f"Semana (7d): {week_pct}% · reseta {usage.get('week_resets', '?')}")
        self.tray.setToolTip("\n".join(lines))

    # -- bandeja -----------------------------------------------------------
    def _aggregate_status(self) -> str:
        statuses = self.panel.statuses()
        for status in STATUS_PRIORITY:
            if status in statuses:
                return status
        return "idle"

    # -- mascote único -----------------------------------------------------------
    def _entries_for(self, status: str) -> list[tuple[str, str | None, str | None]]:
        """Sessões no status dado, em ordem de chegada (a que está nesse
        status há mais tempo primeiro) — para o mascote revezar entre elas."""
        sids = [sid for sid, s in self._statuses.items() if s == status]
        sids.sort(key=lambda sid: self._status_since.get(sid, 0.0))
        return [(self._labels.get(sid, sid), self._messages.get(sid), self._activities.get(sid)) for sid in sids]

    def _update_mascot(self) -> None:
        self.mascot_overlay.sync(self._entries_for("error"), self._entries_for("working"))

    def _update_tray_icon(self, status: str) -> None:
        pixmap = QPixmap(64, 64)
        pixmap.fill(QColor(0, 0, 0, 0))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(LIGHT_COLORS.get(status, LIGHT_COLORS["idle"]))
        painter.drawEllipse(6, 6, 52, 52)
        painter.end()
        self.tray.setIcon(QIcon(pixmap))

    def _rebuild_menu(self) -> None:
        self.menu.clear()

        toggle = QAction("Ocultar" if self.panel.isVisible() else "Mostrar", self.menu)
        toggle.triggered.connect(self._toggle_panel)
        self.menu.addAction(toggle)

        settings_action = QAction("Configurações...", self.menu)
        settings_action.triggered.connect(self._open_settings)
        self.menu.addAction(settings_action)

        self.menu.addSeparator()
        quit_action = QAction("Sair", self.menu)
        quit_action.triggered.connect(QApplication.quit)
        self.menu.addAction(quit_action)

    def _open_settings(self) -> None:
        if self._settings_dialog is None:
            self._settings_dialog = SettingsDialog(self.config, self._on_config_changed, parent=self.panel)
        self._settings_dialog.show()
        self._settings_dialog.raise_()
        self._settings_dialog.activateWindow()

    def _on_config_changed(self, config: Config) -> None:
        config.save()
        self.mascot_overlay.update_config(config)
        self.panel.set_usage_config(config.usage_bar_enabled, config.usage_thresholds)
        self._sync_mascot_visibility()
        self._update_account_usage_badge()

    def _toggle_panel(self) -> None:
        showing = not self.panel.isVisible()
        self.panel.setVisible(showing)
        # só conta como "escondido manualmente" se ainda há sessões — do
        # contrário isso conflitaria com o auto-hide de "sem sessões".
        self._manually_hidden = (not showing) and bool(self._statuses)
        self._update_tray_icon(self._aggregate_status())
        self._sync_mascot_visibility()

    def _sync_panel_visibility(self) -> None:
        if self._statuses:
            if not self._manually_hidden:
                self.panel.show()
        else:
            self.panel.hide()
            self._manually_hidden = False
        self._sync_mascot_visibility()

    def _sync_mascot_visibility(self) -> None:
        # o mascote e a caixa de cota são independentes: desligar "Mostrar
        # mascote" só tira o personagem (e o balão) da janela — a caixa de
        # cota, se habilitada e com dado disponível, continua aparecendo
        # sozinha na mesma posição (ver MascotOverlay._relayout).
        base_visible = bool(self._statuses) and not self._manually_hidden
        want_mascot = base_visible and self.config.mascot_enabled
        want_badge = base_visible and self.config.account_usage_badge_enabled and self.mascot_overlay.has_badge_content
        self.mascot_overlay.set_visible_animated(want_mascot or want_badge)

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._toggle_panel()
