"""Instala (ou atualiza) os hooks do Semáforo de Status em ~/.claude/settings.json.

Existe porque o próprio settings.json não faz parte deste projeto (fica fora,
em ~/.claude/) — se você trocar de máquina ou reclonar o repositório, os
hooks que fazem o painel reagir ao Claude Code em tempo real somem. Rode este
script uma vez em cada máquina (ou de novo, sempre que atualizar os hooks
deste projeto) para (re)instalá-los.

Uso: python3 hooks/install.py
"""
import json
from pathlib import Path

SETTINGS_PATH = Path.home() / ".claude" / "settings.json"
HOOK_SCRIPT = str((Path(__file__).resolve().parent / "status_hook.py"))
MARKER = "status_hook.py"  # usado para identificar (e substituir) nossos hooks numa reinstalação

STATUSLINE_SCRIPT = str((Path(__file__).resolve().parent / "statusline_hook.py"))
STATUSLINE_MARKER = "statusline_hook.py"


def _cmd(status: str) -> dict:
    return {
        "type": "command",
        "command": f'python3 "{HOOK_SCRIPT}" {status} 2>/dev/null || true',
    }


def _statusline_cmd() -> dict:
    return {
        "type": "command",
        "command": f'python3 "{STATUSLINE_SCRIPT}" 2>/dev/null || true',
    }


def _is_statusline_ours(entry: dict | None) -> bool:
    return bool(entry) and STATUSLINE_MARKER in entry.get("command", "")


# evento -> (matcher ou None, status a reportar)
MANAGED_HOOKS = {
    "SessionStart": (None, "idle"),
    "UserPromptSubmit": (None, "working"),
    "PreToolUse": ("", "working"),
    "Notification": ("permission_prompt|idle_prompt|agent_needs_input", "error"),
    "PermissionRequest": (None, "error"),  # qualquer ferramenta pedindo permissão pausa a sessão -> vermelho
    "PostToolUse": ("", "working"),
    "PostToolUseFailure": (None, "error"),
    "PreCompact": (None, "working"),  # /compact (manual ou automático por contexto cheio) começou
    "PostCompact": (None, "idle"),  # compactação terminou -> volta a idle e recalcula tokens
    "StopFailure": (None, "error"),  # turno terminou por erro de API (rate limit, sobrecarga, etc.)
    "Stop": (None, "idle"),
    "SessionEnd": (None, "remove"),
}


def _group(matcher: str | None, status: str) -> dict:
    group = {"hooks": [_cmd(status)]}
    if matcher is not None:
        group["matcher"] = matcher
    return group


def _is_ours(group: dict) -> bool:
    return any(MARKER in h.get("command", "") for h in group.get("hooks", []))


def install(quiet: bool = False) -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    if SETTINGS_PATH.exists():
        settings = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    else:
        settings = {}

    hooks = settings.setdefault("hooks", {})

    for event, (matcher, status) in MANAGED_HOOKS.items():
        existing = hooks.get(event, [])
        kept = [g for g in existing if not _is_ours(g)]
        kept.append(_group(matcher, status))
        hooks[event] = kept

    existing_statusline = settings.get("statusLine")
    statusline_installed = existing_statusline is None or _is_statusline_ours(existing_statusline)
    if statusline_installed:
        settings["statusLine"] = _statusline_cmd()

    SETTINGS_PATH.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if not quiet:
        print(f"Hooks instalados em {SETTINGS_PATH}")
        for event in MANAGED_HOOKS:
            print(f"  - {event}")
        if statusline_installed:
            print("  - statusLine (uso de tokens por sessão)")
        else:
            print(
                "  statusLine customizado já configurado — não sobrescrito;"
                " uso de tokens por sessão ficará indisponível até remover"
                " o statusLine atual do settings.json."
            )


def is_up_to_date() -> bool:
    """Confere se todos os hooks gerenciados em settings.json já apontam
    para o HOOK_SCRIPT atual (ex.: detecta o projeto ter sido movido/renomeado
    desde a última instalação)."""
    if not SETTINGS_PATH.exists():
        return False
    try:
        settings = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False

    hooks = settings.get("hooks", {})
    hooks_ok = all(
        _group(matcher, status) in hooks.get(event, [])
        for event, (matcher, status) in MANAGED_HOOKS.items()
    )

    existing_statusline = settings.get("statusLine")
    if existing_statusline is not None and not _is_statusline_ours(existing_statusline):
        statusline_ok = True  # statusLine customizado do usuário — não é nosso, não mexe
    else:
        statusline_ok = existing_statusline == _statusline_cmd()

    return hooks_ok and statusline_ok


def main() -> None:
    install()


if __name__ == "__main__":
    main()
