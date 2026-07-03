"""Hook do Claude Code que atualiza o Semáforo de Status automaticamente.

Chamado pelo próprio Claude Code (configurado em settings.json) em eventos do
ciclo de vida da sessão. Lê o payload JSON que o Claude Code manda pelo
stdin para descobrir o session_id e o diretório do projeto, e escreve (ou
remove) o status correspondente.

Uso: status_hook.py <idle|working|error|remove>
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from status_store import remove_status, write_status  # noqa: E402


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] not in ("idle", "working", "error", "remove"):
        print("uso: status_hook.py <idle|working|error|remove>", file=sys.stderr)
        sys.exit(1)

    target = sys.argv[1]

    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        payload = {}

    session_id = payload.get("session_id") or "claude-code-desconhecido"
    cwd = payload.get("cwd")
    label = Path(cwd).name if cwd else session_id[:8]

    if target == "remove":
        remove_status(session_id)
    else:
        write_status(session_id, target, label=label)


if __name__ == "__main__":
    main()
