"""Hook do Claude Code que atualiza o Semáforo de Status automaticamente.

Chamado pelo próprio Claude Code (configurado em settings.json) em eventos do
ciclo de vida da sessão. Lê o payload JSON que o Claude Code manda pelo
stdin para descobrir o session_id e o diretório do projeto, e escreve (ou
remove) o status correspondente.

Uso: status_hook.py <idle|working|error|remove>
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from status_store import remove_status, write_status  # noqa: E402

# eventos em que vale a pena montar uma mensagem pro balão de fala do
# mascote; nos demais (ex.: cada PreToolUse) isso rodaria a cada chamada de
# ferramenta à toa, então só limpamos o balão.
MESSAGE_EVENTS = {"Stop", "Notification", "PermissionRequest"}
TRANSCRIPT_SCAN_LINES = 50
# pequena folga antes de ler o transcript no Stop: a última mensagem do
# assistente pode ainda não ter sido gravada em disco no instante exato em
# que o hook dispara (visto na prática — sem isso, às vezes pega a
# penúltima mensagem em vez da resposta final de verdade).
STOP_READ_DELAY_SECONDS = 0.25

# tool_name (PreToolUse/PostToolUse) -> atividade, pra escolher uma pose do
# mascote coerente com o que está acontecendo de verdade em vez de sortear
# à toa. Ferramentas fora deste mapa (ex.: Task, MCPs) caem no sorteio.
TOOL_ACTIVITY = {
    "Bash": "processing",
    "Edit": "writing",
    "Write": "writing",
    "NotebookEdit": "writing",
    "Read": "searching",
    "Grep": "searching",
    "Glob": "searching",
    "WebSearch": "searching",
    "WebFetch": "searching",
}


def _activity_for(payload: dict) -> str | None:
    event = payload.get("hook_event_name")
    if event == "UserPromptSubmit":
        return "thinking"  # ainda não chamou nenhuma ferramenta
    if event in ("PreToolUse", "PostToolUse"):
        return TOOL_ACTIVITY.get(payload.get("tool_name"))
    return None


def _last_assistant_text(transcript_path: str | None, delay: float = 0.0) -> str | None:
    """Lê o fim do transcript (formato interno do Claude Code, não
    documentado oficialmente — pode mudar entre versões) e devolve o texto
    da última resposta do assistente, ou None se não achar/der erro."""
    if not transcript_path:
        return None
    if delay:
        time.sleep(delay)
    try:
        lines = Path(transcript_path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in reversed(lines[-TRANSCRIPT_SCAN_LINES:]):
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            # uma linha isolada mal formada (ex.: escrita ainda em andamento)
            # não deve derrubar a busca inteira — só pula pra anterior.
            continue
        if entry.get("type") != "assistant":
            continue
        content = entry.get("message", {}).get("content", [])
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text" and block.get("text"):
                return block["text"]
    return None


def _pending_request_text(payload: dict) -> str | None:
    """Monta o texto do pedido que está deixando a sessão vermelha (pedido
    de permissão de ferramenta, ou notificação), a partir do payload do
    próprio hook — não do transcript, que não tem essa informação."""
    try:
        event = payload.get("hook_event_name")

        if event == "PermissionRequest":
            tool_name = payload.get("tool_name")
            tool_input = payload.get("tool_input") or {}

            if tool_name == "AskUserQuestion":
                questions = tool_input.get("questions") or []
                if questions:
                    question = questions[0].get("question", "")
                    options = questions[0].get("options") or []
                    if options:
                        labels = ", ".join(o.get("label", "") for o in options[:4] if o.get("label"))
                        return f"{question} ({labels})" if labels else question
                    return question or None

            if tool_name == "Bash":
                return tool_input.get("description") or tool_input.get("command") or None

            if tool_name:
                return f"Precisa de permissão para usar {tool_name}"

        if event == "Notification":
            message = payload.get("message")
            if message:
                return message
    except Exception:
        return None
    return None


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
        message = None
        event = payload.get("hook_event_name")
        if event in MESSAGE_EVENTS:
            if event in ("Notification", "PermissionRequest"):
                message = _pending_request_text(payload) or _last_assistant_text(payload.get("transcript_path"))
            else:
                message = _last_assistant_text(payload.get("transcript_path"), delay=STOP_READ_DELAY_SECONDS)
        activity = _activity_for(payload)
        write_status(session_id, target, label=label, message=message, activity=activity)


if __name__ == "__main__":
    main()
