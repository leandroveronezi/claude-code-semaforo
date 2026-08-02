"""Configuração central de logging: arquivo rotativo e limitado em tamanho
(nunca "enche o pc"), pra dar rastro de falhas sem depender do usuário rodar
o app num terminal pra ver stderr — o caso comum aqui é autostart/bandeja,
onde stderr não vai a lugar nenhum.

Nível padrão é INFO; `SEMAFORO_DEBUG=1` no ambiente sobe pra DEBUG (mesma
convenção de SEMAFORO_STATUS_DIR/SEMAFORO_SKIP_HOOK)."""
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_DIR = Path.home() / ".config" / "semaforo-status" / "logs"
MAX_BYTES = 1_000_000  # ~1MB por arquivo
BACKUP_COUNT = 3  # arquivo atual + 3 rotacionados -> ~4MB de teto por logger

_configured_loggers: set[str] = set()


def setup_logging(logger_name: str, filename: str) -> logging.Logger:
    """Configura um logger com rotação de arquivo em
    ~/.config/semaforo-status/logs/<filename>. Idempotente: chamar de novo
    com o mesmo logger_name (de módulos diferentes que importam este helper
    no mesmo processo) não duplica handlers."""
    logger = logging.getLogger(logger_name)
    if logger_name in _configured_loggers:
        return logger
    _configured_loggers.add(logger_name)

    logger.setLevel(logging.DEBUG if os.environ.get("SEMAFORO_DEBUG") else logging.INFO)
    logger.propagate = False

    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            LOG_DIR / filename, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
        )
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        logger.addHandler(handler)
    except OSError as exc:
        # único lugar onde uma falha realmente não pode virar log nenhum
        # (é o próprio logger que não montou) — stderr é a última rede,
        # pra não ficarmos sem rastro nenhum de "por que não há logs".
        print(f"semaforo: não foi possível configurar log em arquivo: {exc}", file=sys.stderr)

    return logger
