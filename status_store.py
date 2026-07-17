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
    payload = {
        "session_id": session_id,
        "status": status,
        "label": label or session_id,
        "message": message,
        "activity": activity,
        "pid_chain": pid_chain or [],
        "updated_at": time.time(),
    }

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
