"""Descobre sessões monitoradas (um arquivo de status = um editor/aba) e
mantém o painel único de semáforos e o ícone de bandeja sincronizados com elas."""
import shutil
import subprocess
import time
from pathlib import Path

from PyQt6.QtCore import QFileSystemWatcher, QPoint, QSettings, Qt, QTimer
from PyQt6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from light_column import LIGHT_COLORS
from semaphore_panel import SemaphorePanel
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
        self.panel.show()
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
            previous_status = self._statuses.get(session_id)
            self._labels[session_id] = label
            self._statuses[session_id] = status
            self.panel.upsert_session(session_id, label, status)
            if status == "error" and previous_status != "error":
                self._play_alert_sound()
                self._notify_desktop(label)

        for session_id in list(self._updated_at):
            if session_id not in seen:
                del self._updated_at[session_id]
                self._statuses.pop(session_id, None)
                self._labels.pop(session_id, None)
                self.panel.remove_session(session_id)

        self._update_tray_icon(self._aggregate_status())
        self._resync_watched_files(paths)

    def _play_alert_sound(self) -> None:
        # QApplication.beep() usa o "system bell" do X11, que em muitos
        # ambientes (KDE Plasma incluso) fica sem áudio de verdade roteado —
        # paplay/pw-play tocam um som real pelo servidor de áudio.
        for player in ("paplay", "pw-play"):
            if shutil.which(player) and ALERT_SOUND.exists():
                try:
                    subprocess.Popen(
                        [player, *ALERT_VOLUME_ARGS[player], str(ALERT_SOUND)],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    return
                except OSError:
                    continue
        QApplication.beep()

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

        self.menu.addSeparator()
        quit_action = QAction("Sair", self.menu)
        quit_action.triggered.connect(QApplication.quit)
        self.menu.addAction(quit_action)

    def _toggle_panel(self) -> None:
        self.panel.setVisible(not self.panel.isVisible())
        self._update_tray_icon(self._aggregate_status())

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._toggle_panel()
