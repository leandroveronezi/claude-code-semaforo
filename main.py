"""Semáforo de Status: um semáforo flutuante por editor/aba monitorado."""
import shutil
import signal
import subprocess
import sys

from PyQt6.QtWidgets import QApplication

from hooks.install import install, is_up_to_date
from logging_setup import setup_logging
from semaphore_panel import SemaphorePanel
from session_manager import SessionManager

logger = setup_logging("semaforo", "semaforo.log")


def _log_uncaught_exception(exc_type, exc_value, exc_tb) -> None:
    # sem isso, uma exceção que escapa do loop de eventos do Qt só aparece
    # no stderr — invisível de verdade quando o app sobe via autostart ou
    # pela bandeja, sem terminal nenhum grudado nele.
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return
    logger.critical("Exceção não tratada", exc_info=(exc_type, exc_value, exc_tb))
    sys.__excepthook__(exc_type, exc_value, exc_tb)


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
    except (OSError, ValueError):
        # ValueError cobre json.JSONDecodeError: install() lê settings.json
        # sem tratar esse caso (diferente de is_up_to_date(), que já trata),
        # então um settings.json corrompido chegava até aqui sem ser pego só
        # por OSError — derrubava o app inteiro antes do QApplication existir.
        logger.warning("Não foi possível instalar/atualizar hooks em ~/.claude/settings.json", exc_info=True)
        return  # settings.json inacessível/corrompido não deve impedir o painel de abrir

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
    # sem isso, um Ctrl+C que chega no meio de um paintEvent (callback do
    # Qt em C++) faz o Python levantar KeyboardInterrupt ali dentro, o que
    # não é seguro de propagar através da pilha C++ — derruba o processo
    # com abort/core dump em vez de só sair. SIG_DFL faz o SO encerrar o
    # processo diretamente, sem passar pelo Python nesse ponto.
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    sys.excepthook = _log_uncaught_exception

    logger.info("Iniciando semáforo de status")
    _ensure_hooks_installed()

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # continua rodando mesmo com o painel oculto

    # sem isso, ⚠️/🔴/etc. no balão do mascote e nos campos de configuração
    # caem no fallback padrão do Qt e viram um "tofu" monocromático — colocar
    # a Noto Color Emoji como fallback (não como família principal) resolve
    # sem afetar o texto normal, e sem precisar embutir a fonte no projeto
    # (já vem instalada na maioria das distros Linux).
    default_font = app.font()
    default_font.setFamilies([default_font.family(), "Noto Color Emoji"])
    app.setFont(default_font)

    panel = SemaphorePanel()
    manager = SessionManager(panel)
    manager.start()

    exit_code = app.exec()
    logger.info("Encerrando semáforo de status (exit_code=%s)", exit_code)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
