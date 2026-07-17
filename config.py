"""Preferências do usuário (personagem, som, mascote, beep), persistidas em YAML."""
from dataclasses import asdict, dataclass
from pathlib import Path

import yaml

CONFIG_PATH = Path.home() / ".config" / "semaforo-status" / "config.yaml"

DEFAULT_MASCOT = "Clippy"


@dataclass
class Config:
    mascot: str = DEFAULT_MASCOT
    mascot_enabled: bool = True
    mascot_scale: int = 100  # % do tamanho original do mascote (100 = tamanho padrão/atual)
    mascot_sounds_enabled: bool = True
    alert_beep_enabled: bool = True
    notification_enabled: bool = True
    mascot_rotation_seconds: float = 4.5  # tempo de cada sessão em erro/working, e de cada item (não-último) na fila ociosa
    mascot_idle_last_seconds: float = 9.0  # tempo do último item da fila ociosa antes de tudo sumir
    mascot_message_limit: int = 150  # nº de caracteres exibidos no balão antes de truncar com "…"

    @classmethod
    def load(cls) -> "Config":
        try:
            raw = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            return cls()
        known_fields = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in raw.items() if k in known_fields})

    def save(self) -> None:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(yaml.safe_dump(asdict(self), allow_unicode=True), encoding="utf-8")
