"""Preferências do usuário (personagem, som, mascote, beep), persistidas em YAML."""
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

from logging_setup import setup_logging

logger = setup_logging("semaforo", "semaforo.log")

CONFIG_PATH = Path.home() / ".config" / "semaforo-status" / "config.yaml"

DEFAULT_MASCOT = "Clippy"

# limiares de cor da barra de uso de tokens: [tokens_acumulados, cor_hex],
# em ordem crescente. Acima do último valor, a barra fica cheia na última cor.
DEFAULT_USAGE_THRESHOLDS = [
    [100_000, "#32d74b"],
    [150_000, "#ffd60a"],
    [200_000, "#ff9f0a"],
    [300_000, "#ff453a"],
]

# limiares de aviso de contexto: [tokens_acumulados, mensagem, habilitado].
# cada linha dispara um aviso (balão do mascote + notificação) uma única vez
# ao atingir o valor; só pode disparar de novo depois que os tokens caírem
# abaixo de (tokens - token_alert_reset_margin) — ver Config.token_alert_reset_margin.
# `mensagem` é o texto completo do aviso (emoji incluso), com placeholders
# {tokens} (total acumulado formatado), {session} (nome/label da sessão) e
# {threshold} (valor do limiar formatado).
DEFAULT_TOKEN_ALERT_THRESHOLDS = [
    [100_000, "⚠️ {tokens} tokens acumulados na {session} — considere rodar /compact", True],
    [200_000, "🔴 {tokens} tokens acumulados na {session} — considere rodar /compact", True],
]

# usado só como rede de segurança se o texto de um limiar tiver um placeholder
# inválido (ex.: {toekns}) e `str.format` estourar — nunca editável pelo usuário.
DEFAULT_TOKEN_ALERT_MESSAGE = "⚠️ {tokens} tokens acumulados na {session} — considere rodar /compact"

_DEFAULT_TOKEN_ALERT_TEXT = "{symbol} {tokens} tokens acumulados na {session} — considere rodar /compact"

# limiares de aviso de cota da conta: [percentual, mensagem, habilitado].
# mesma mecânica dos avisos de contexto (dispara uma vez ao atingir o
# percentual, rearma com histerese), mas usando o % de uso da cota (raspado
# de /usage via account_usage.py) em vez de tokens acumulados na sessão.
# `mensagem` aceita os placeholders {pct} (percentual atual) e {reset}
# (horário de reset, como exibido pelo próprio /usage).
DEFAULT_SESSION_PCT_ALERT_THRESHOLDS = [
    [80, "⚠️ Sessão (5h) em {pct}% — reseta {reset}", True],
    [95, "🔴 Sessão (5h) em {pct}% — reseta {reset}", True],
]
DEFAULT_WEEK_PCT_ALERT_THRESHOLDS = [
    [80, "⚠️ Semana (7d) em {pct}% — reseta {reset}", True],
    [95, "🔴 Semana (7d) em {pct}% — reseta {reset}", True],
]

# usados só como rede de segurança se o texto de um limiar tiver um
# placeholder inválido e `str.format` estourar — nunca editáveis pelo usuário.
DEFAULT_SESSION_PCT_ALERT_MESSAGE = "⚠️ Sessão (5h) em {pct}%"
DEFAULT_WEEK_PCT_ALERT_MESSAGE = "⚠️ Semana (7d) em {pct}%"


def _migrate_token_alert_row(row: list) -> list:
    """Converte formatos antigos de linha pro atual [tokens, mensagem, habilitado].

    Formatos já vistos em configs salvos:
    - [tokens, símbolo, habilitado] (formato original)
    - [tokens, símbolo, habilitado, mensagem] (formato intermediário, símbolo + template global)
    - [tokens, mensagem, habilitado] (formato atual, nada a migrar)
    """
    if len(row) == 4:
        tokens, symbol, enabled, message = row
        message = (message or "").strip()
        text = message.replace("{symbol}", symbol) if message else _DEFAULT_TOKEN_ALERT_TEXT.format(
            symbol=symbol, tokens="{tokens}", session="{session}"
        )
        return [tokens, text, enabled]
    if len(row) == 3:
        tokens, second, enabled = row
        if isinstance(second, str) and "{" not in second and len(second) <= 10:
            # símbolo curto do formato original, sem mensagem própria.
            text = _DEFAULT_TOKEN_ALERT_TEXT.format(symbol=second, tokens="{tokens}", session="{session}")
            return [tokens, text, enabled]
        return [tokens, second, enabled]
    return list(row)


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
    usage_bar_enabled: bool = True
    usage_thresholds: list = field(default_factory=lambda: [row[:] for row in DEFAULT_USAGE_THRESHOLDS])
    account_usage_badge_enabled: bool = True  # caixa de cota da conta (Sessão 5h / Semana 7d) abaixo do mascote
    token_alert_thresholds: list = field(default_factory=lambda: [row[:] for row in DEFAULT_TOKEN_ALERT_THRESHOLDS])
    token_alert_reset_margin: int = 20_000  # tokens abaixo do limiar pra rearmar o aviso (histerese)
    session_pct_alert_thresholds: list = field(
        default_factory=lambda: [row[:] for row in DEFAULT_SESSION_PCT_ALERT_THRESHOLDS]
    )
    session_pct_alert_reset_margin: int = 10  # pontos percentuais abaixo do limiar pra rearmar o aviso (histerese)
    week_pct_alert_thresholds: list = field(
        default_factory=lambda: [row[:] for row in DEFAULT_WEEK_PCT_ALERT_THRESHOLDS]
    )
    week_pct_alert_reset_margin: int = 10  # pontos percentuais abaixo do limiar pra rearmar o aviso (histerese)
    last_notified_release: str = ""  # última tag de release já avisada (ver update_checker.py) — evita reavisar a mesma versão a cada restart

    @classmethod
    def load(cls) -> "Config":
        try:
            raw = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
        except FileNotFoundError:
            return cls()  # primeira execução, sem config salvo ainda -> nada de anormal
        except (OSError, yaml.YAMLError):
            logger.warning("Config em %s inválido/ilegível; usando padrões", CONFIG_PATH, exc_info=True)
            return cls()
        known_fields = {f for f in cls.__dataclass_fields__}
        data = {k: v for k, v in raw.items() if k in known_fields}
        if "token_alert_thresholds" in data:
            data["token_alert_thresholds"] = [
                _migrate_token_alert_row(row) for row in data["token_alert_thresholds"]
            ]
        return cls(**data)

    def save(self) -> None:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(yaml.safe_dump(asdict(self), allow_unicode=True), encoding="utf-8")
