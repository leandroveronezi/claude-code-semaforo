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
    mascot_sounds_enabled: bool = True
    alert_beep_enabled: bool = True

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
