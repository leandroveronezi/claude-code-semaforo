"""Descobre sessões monitoradas (um arquivo de status = um editor/aba) e
mantém o painel único de semáforos e o ícone de bandeja sincronizados com elas."""
import shutil
import subprocess
import time
from pathlib import Path

from PyQt6.QtCore import QFileSystemWatcher, QPoint, QSettings, Qt, QTimer
from PyQt6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from audio import play_sound
from config import Config
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


class SessionManager:
    def __init__(self, panel: SemaphorePanel, directory: Path | None = None):
        self.panel = panel
        self.directory = directory or sessions_dir()
        self._updated_at: dict[str, float] = {}
        self._statuses: dict[str, str] = {}
        self._labels: dict[str, str] = {}
        self._messages: dict[str, str | None] = {}
        self._activities: dict[str, str | None] = {}
        self._status_since: dict[str, float] = {}  # quando o status atual começou (ordem de chegada p/ mascote)
        self._manually_hidden = False  # usuário escondeu o painel enquanto havia sessões
        self.config = Config.load()
        self.mascot_overlay = MascotOverlay(self.config)
        self._settings_dialog: SettingsDialog | None = None
        self.settings = QSettings("SemaforoStatus", "Posicoes")

        saved_pos = self.settings.value(SETTINGS_KEY)
        if isinstance(saved_pos, QPoint):
            self.panel.move(saved_pos)
        self.panel.moved.connect(lambda pos: self.settings.setValue(SETTINGS_KEY, pos))
        self.panel.right_clicked.connect(self._toggle_panel)

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

        self.tray = QSystemTrayIcon()
        self.tray.setToolTip("Semáforo de Status")
        self.menu = QMenu()
        self.tray.setContextMenu(self.menu)
        self.menu.aboutToShow.connect(self._rebuild_menu)
        self.tray.activated.connect(self._on_tray_activated)

        self._update_tray_icon("idle")
        self.tray.show()

    def start(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        self.watcher.addPath(str(self.directory))
        self._scan()
        self.fallback_timer.start()
        self.stale_timer.start()

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
            if status != previous_status:
                self._status_since[session_id] = time.time()
                # "chegou" numa sessão ociosa vindo de outro estado -> notificação
                # passageira na fila do mascote; sessão nova descoberta já ociosa
                # (previous_status is None) não conta como chegada.
                if status == "idle" and previous_status is not None:
                    self.mascot_overlay.enqueue_idle(label, message)
            self.panel.upsert_session(session_id, label, status, message)
            if status == "error" and previous_status != "error":
                self._play_alert_sound()
                self._notify_desktop(label)

        for session_id in list(self._updated_at):
            if session_id not in seen:
                del self._updated_at[session_id]
                self._statuses.pop(session_id, None)
                self._labels.pop(session_id, None)
                self._messages.pop(session_id, None)
                self._activities.pop(session_id, None)
                self._status_since.pop(session_id, None)
                self.panel.remove_session(session_id)

        self._update_tray_icon(self._aggregate_status())
        self._update_mascot()
        self._sync_panel_visibility()
        self._resync_watched_files(paths)

    def _play_alert_sound(self) -> None:
        if self.config.alert_beep_enabled:
            play_sound(ALERT_SOUND, ALERT_VOLUME_ARGS)

    def _notify_desktop(self, label: str) -> None:
        if not shutil.which("notify-send"):
            return
        try:
            subprocess.Popen(
                ["notify-send", "-a", "Semáforo de Status", "-i", "dialog-warning", label, "Precisa da sua atenção"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            pass

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
        self._sync_mascot_visibility()

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
        want_visible = bool(self._statuses) and self.config.mascot_enabled and not self._manually_hidden
        self.mascot_overlay.set_visible_animated(want_visible)

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._toggle_panel()
