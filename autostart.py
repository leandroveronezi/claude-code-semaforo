"""Liga/desliga o Semáforo de Status na inicialização do sistema (login).

Usa o mecanismo padrão do freedesktop.org (arquivo .desktop em
~/.config/autostart/), que funciona em qualquer ambiente de desktop Linux
compatível (KDE Plasma, GNOME, XFCE, etc.) sem precisar de systemd.

Uso:
    python3 autostart.py install   # liga
    python3 autostart.py remove    # desliga
    python3 autostart.py status    # mostra se está ligado
"""
import sys
from pathlib import Path

AUTOSTART_DIR = Path.home() / ".config" / "autostart"
DESKTOP_FILE = AUTOSTART_DIR / "semaforo-status.desktop"
MAIN_SCRIPT = str((Path(__file__).resolve().parent / "main.py"))

DESKTOP_ENTRY = f"""[Desktop Entry]
Type=Application
Name=Semáforo de Status
Comment=Painel de status do Claude Code
Exec=python3 "{MAIN_SCRIPT}"
Icon=utilities-system-monitor
Terminal=false
X-GNOME-Autostart-enabled=true
"""


def install() -> None:
    AUTOSTART_DIR.mkdir(parents=True, exist_ok=True)
    DESKTOP_FILE.write_text(DESKTOP_ENTRY, encoding="utf-8")
    print(f"Autostart ativado: {DESKTOP_FILE}")
    print("O painel vai abrir sozinho no próximo login.")


def remove() -> None:
    if DESKTOP_FILE.exists():
        DESKTOP_FILE.unlink()
        print(f"Autostart removido: {DESKTOP_FILE}")
    else:
        print("Autostart já estava desligado (nada a remover).")


def status() -> None:
    if DESKTOP_FILE.exists():
        print(f"Autostart LIGADO ({DESKTOP_FILE})")
    else:
        print("Autostart DESLIGADO")


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] not in ("install", "remove", "status"):
        print("uso: python3 autostart.py <install|remove|status>", file=sys.stderr)
        sys.exit(1)

    {"install": install, "remove": remove, "status": status}[sys.argv[1]]()


if __name__ == "__main__":
    main()
