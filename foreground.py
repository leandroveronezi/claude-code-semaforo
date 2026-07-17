"""Detecta se a janela de uma sessão está em primeiro plano (X11), para não
repetir beep/notificação de erro quando o usuário já está olhando pra ela.

Só funciona em X11 (usa `xprop`); em Wayland ou sem `xprop` disponível,
`active_window_pid()` retorna None e quem chamar deve tratar isso como "não
sabemos" — ou seja, cair no comportamento antigo de sempre alertar, nunca
assumir "está em primeiro plano" por falta de informação.
"""
import re
import subprocess
from pathlib import Path

_ACTIVE_WINDOW_RE = re.compile(r"^_NET_ACTIVE_WINDOW.*#\s*(0x[0-9a-fA-F]+)")
_WM_PID_RE = re.compile(r"^_NET_WM_PID.*=\s*(\d+)")


def active_window_pid() -> int | None:
    """PID dono da janela ativa, via `xprop`. None se não der pra descobrir
    (Wayland, xprop ausente, nenhuma janela ativa, timeout etc.)."""
    try:
        root = subprocess.run(
            ["xprop", "-root", "_NET_ACTIVE_WINDOW"],
            capture_output=True, text=True, timeout=1,
        )
        match = _ACTIVE_WINDOW_RE.match(root.stdout)
        if not match or match.group(1) == "0x0":
            return None

        win = subprocess.run(
            ["xprop", "-id", match.group(1), "_NET_WM_PID"],
            capture_output=True, text=True, timeout=1,
        )
        pid_match = _WM_PID_RE.match(win.stdout)
        return int(pid_match.group(1)) if pid_match else None
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None


def ancestor_pids(pid: int, limit: int = 50) -> list[int]:
    """Sobe a árvore de processos a partir de `pid` (inclusive) até o
    processo 1 ou `limit`, lendo /proc/<pid>/stat. Gravado junto do status de
    cada sessão para, mais tarde, checar se a janela ativa pertence a ela
    (algum ancestral dela é o dono dessa janela)."""
    chain = []
    current = pid
    for _ in range(limit):
        chain.append(current)
        if current <= 1:
            break
        try:
            stat = Path(f"/proc/{current}/stat").read_text()
        except OSError:
            break
        # comm pode ter espaços/parênteses; ppid é o campo logo após o
        # último ')' que fecha o nome do processo.
        fields = stat.rsplit(")", 1)[-1].split()
        try:
            current = int(fields[1])
        except (IndexError, ValueError):
            break
    return chain
