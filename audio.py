"""Reprodução de som compartilhada (alerta de erro + sons do mascote)."""
import shutil
import subprocess
from pathlib import Path

from PyQt6.QtWidgets import QApplication

# QApplication.beep() usa o "system bell" do X11, que em muitos ambientes
# (KDE Plasma incluso) fica sem áudio de verdade roteado — paplay/pw-play
# tocam um som real pelo servidor de áudio.
PLAYERS = ("paplay", "pw-play")


def play_sound(path: Path, volume_args: dict[str, list[str]] | None = None) -> None:
    """Toca um .wav pelo servidor de áudio (paplay/pw-play), com fallback pro
    beep do Qt se nenhum player estiver disponível. `volume_args` (opcional)
    mapeia nome do player -> args extra de volume."""
    volume_args = volume_args or {}
    if path.exists():
        for player in PLAYERS:
            if shutil.which(player):
                try:
                    subprocess.Popen(
                        [player, *volume_args.get(player, []), str(path)],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    return
                except OSError:
                    continue
    QApplication.beep()
