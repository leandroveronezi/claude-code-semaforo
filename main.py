"""Semáforo de Status: um semáforo flutuante por editor/aba monitorado."""
import shutil
import subprocess
import sys

from PyQt6.QtWidgets import QApplication

from hooks.install import install, is_up_to_date
from semaphore_panel import SemaphorePanel
from session_manager import SessionManager


def _ensure_hooks_installed() -> None:
    # O caminho do projeto pode mudar (mover/renomear a pasta) e os hooks em
    # ~/.claude/settings.json ficam apontando pro caminho antigo. Como o
    # comando do hook termina em `|| true`, isso falha em silêncio: o painel
    # simplesmente para de receber status e nada avisa. Reconferimos e
    # corrigimos a cada início pra não depender de rodar hooks/install.py
    # manualmente depois de mover a pasta.
    try:
        if is_up_to_date():
            return
        install(quiet=True)
    except OSError:
        return  # settings.json inacessível não deve impedir o painel de abrir

    if shutil.which("notify-send"):
        subprocess.Popen(
            [
                "notify-send", "-a", "Semáforo de Status", "-i", "dialog-information",
                "Hooks corrigidos", "Rode /hooks nas sessões do Claude Code já abertas para recarregar",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def main() -> int:
    _ensure_hooks_installed()

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # continua rodando mesmo com o painel oculto

    panel = SemaphorePanel()
    manager = SessionManager(panel)
    manager.start()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
