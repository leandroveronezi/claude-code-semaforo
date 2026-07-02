"""Semáforo de Status: um semáforo flutuante por editor/aba monitorado."""
import sys

from PyQt6.QtWidgets import QApplication

from semaphore_panel import SemaphorePanel
from session_manager import SessionManager


def main() -> int:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # continua rodando mesmo com o painel oculto

    panel = SemaphorePanel()
    manager = SessionManager(panel)
    manager.start()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
