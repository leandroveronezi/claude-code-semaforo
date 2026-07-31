"""Leitura/escrita atômica dos arquivos de status das sessões monitoradas."""
import json
import os
import time
from pathlib import Path

STATUSES = ("idle", "working", "error")

DEFAULT_SESSIONS_DIR = Path(__file__).resolve().parent / "sessions"


def sessions_dir() -> Path:
    override = os.environ.get("SEMAFORO_STATUS_DIR")
    path = Path(override) if override else DEFAULT_SESSIONS_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_status(
    session_id: str,
    status: str,
    label: str | None = None,
    directory: Path | None = None,
    message: str | None = None,
    activity: str | None = None,
    pid_chain: list[int] | None = None,
) -> Path:
    if status not in STATUSES:
        raise ValueError(f"status inválido: {status!r} (use um de {STATUSES})")

    directory = directory or sessions_dir()
    target = directory / f"{session_id}.json"

    # o statusLine (hooks/statusline_hook.py) grava "usage" de forma
    # independente e bem mais frequente que os hooks de ciclo de vida; sem
    # isso aqui, qualquer write_status (ex.: PreToolUse) apagaria o uso de
    # tokens que acabou de chegar.
    previous = read_status(target)
    usage = previous.get("usage") if previous else None

    payload = {
        "session_id": session_id,
        "status": status,
        "label": label or session_id,
        "message": message,
        "activity": activity,
        "pid_chain": pid_chain or [],
        "usage": usage,
        "updated_at": time.time(),
    }

    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    os.replace(tmp, target)
    return target


def update_usage(
    session_id: str,
    usage: dict,
    label: str | None = None,
    directory: Path | None = None,
) -> Path:
    """Atualiza só o uso de tokens/contexto de uma sessão, preservando
    status/label/message já conhecidos por outros hooks. Se a sessão ainda
    não existir (statusLine chegou antes do primeiro hook de ciclo de vida),
    cria um registro "idle" mínimo."""
    directory = directory or sessions_dir()
    target = directory / f"{session_id}.json"

    previous = read_status(target)
    if previous is None:
        previous = {
            "session_id": session_id,
            "status": "idle",
            "label": label or session_id,
            "message": None,
            "activity": None,
            "pid_chain": [],
        }

    # merge raso: statusline_hook.py (custo/contexto) e status_hook.py
    # (tokens acumulados via transcript) escrevem campos diferentes dentro
    # de "usage" — um não pode apagar o que o outro já gravou.
    merged_usage = {**(previous.get("usage") or {}), **usage}
    payload = {**previous, "usage": merged_usage, "updated_at": time.time()}

    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    os.replace(tmp, target)
    return target


def read_status(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    if data.get("status") not in STATUSES:
        return None
    return data


def remove_status(session_id: str, directory: Path | None = None) -> None:
    directory = directory or sessions_dir()
    target = directory / f"{session_id}.json"
    target.unlink(missing_ok=True)
