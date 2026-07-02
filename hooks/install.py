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

def _cmd(status: str) -> dict:
    return {
        "type": "command",
        "command": f'python3 "{HOOK_SCRIPT}" {status} 2>/dev/null || true',
    }


# evento -> (matcher ou None, status a reportar)
MANAGED_HOOKS = {
    "SessionStart": (None, "idle"),
    "UserPromptSubmit": (None, "working"),
    "PreToolUse": ("", "working"),
    "Notification": ("permission_prompt", "error"),
    "PermissionRequest": ("AskUserQuestion|Bash", "error"),
    "PostToolUse": ("", "working"),
    "PostToolUseFailure": (None, "error"),
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


def main() -> None:
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

    SETTINGS_PATH.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Hooks instalados em {SETTINGS_PATH}")
    for event in MANAGED_HOOKS:
        print(f"  - {event}")


if __name__ == "__main__":
    main()
