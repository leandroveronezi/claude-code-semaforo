"""Comando de statusLine do Claude Code que alimenta o Semáforo de Status
com uso de tokens/contexto por sessão.

Diferente de hooks/status_hook.py (eventos pontuais do ciclo de vida), este
script é chamado pelo próprio Claude Code repetidamente ao longo da sessão
(a cada mensagem do assistente, troca de modo, etc., com debounce de
~300ms) e recebe no stdin custo/uso de contexto que não existe no payload
dos hooks normais. Também imprime uma linha simples no stdout, já que
configurar "statusLine" substitui a barra de status nativa do Claude Code.

Uso: statusline_hook.py (chamado pelo Claude Code, não à mão)
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from logging_setup import setup_logging  # noqa: E402
from status_store import update_usage  # noqa: E402

logger = setup_logging("semaforo.hooks", "hooks.log")


def _render_statusline(payload: dict, context_window: dict, cost: dict) -> str:
    parts = []
    model = payload.get("model", {}).get("display_name")
    if model:
        parts.append(f"[{model}]")
    used_pct = context_window.get("used_percentage")
    if used_pct is not None:
        parts.append(f"{used_pct}% ctx")
    total_cost = cost.get("total_cost_usd")
    if total_cost is not None:
        parts.append(f"${total_cost:.4f}")
    return " ".join(parts) if parts else ""


def main() -> None:
    if os.environ.get("SEMAFORO_SKIP_HOOK"):
        return

    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        payload = {}

    session_id = payload.get("session_id")
    if not session_id:
        return

    cwd = payload.get("cwd")
    label = Path(cwd).name if cwd else session_id[:8]

    context_window = payload.get("context_window") or {}
    cost = payload.get("cost") or {}
    current_usage = context_window.get("current_usage") or {}

    usage = {
        "used_percentage": context_window.get("used_percentage"),
        "context_window_size": context_window.get("context_window_size"),
        "total_input_tokens": context_window.get("total_input_tokens"),
        "total_output_tokens": context_window.get("total_output_tokens"),
        "cache_creation_input_tokens": current_usage.get("cache_creation_input_tokens"),
        "cache_read_input_tokens": current_usage.get("cache_read_input_tokens"),
        "total_cost_usd": cost.get("total_cost_usd"),
    }
    update_usage(session_id, usage, label=label)

    print(_render_statusline(payload, context_window, cost))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logger.exception("Falha não tratada no statusLine hook")
