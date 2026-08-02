"""Verifica se há uma release mais nova publicada no GitHub do que a versão
local instalada (ver version.py).

Não existe instalador nem gatilho de update automático — o app é consumido
via `git clone`/`git pull` manual — então "nova versão disponível" aqui
significa só "a última release publicada no GitHub é mais nova que
__version__". Cabe ao usuário decidir se e quando atualizar; ver o disparo
do aviso em SessionManager._poll_update_check."""
import json
import urllib.error
import urllib.request

from logging_setup import setup_logging
from version import __version__

logger = setup_logging("semaforo", "semaforo.log")

REPO = "leandroveronezi/claude-code-semaforo"
LATEST_RELEASE_API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE_URL = f"https://github.com/{REPO}/releases/latest"
REQUEST_TIMEOUT_SECONDS = 10


def _version_tuple(tag: str) -> tuple[int, ...]:
    """'v1.2.3' -> (1, 2, 3). Sufixo não numérico num componente (ex.: a parte
    "3-beta" de "v1.2.3-beta") vira 0 em vez de estourar, pra uma tag fora do
    padrão semver simples não quebrar a comparação."""
    cleaned = tag.strip().lstrip("vV")
    parts = []
    for chunk in cleaned.split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts) or (0,)


def is_newer(remote_tag: str) -> bool:
    return _version_tuple(remote_tag) > _version_tuple(__version__)


def fetch_latest_release() -> "dict | None":
    """Bloqueante (requisição de rede) — chamar de fora da thread da UI (ver
    _UpdateCheckThread em session_manager.py). Retorna None em qualquer falha
    (sem rede, rate limit do GitHub, repo ainda sem nenhuma release
    publicada): best-effort, nunca deve interromper o app nem gerar erro
    visível pro usuário."""
    request = urllib.request.Request(
        LATEST_RELEASE_API_URL,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "semaforo-status-update-checker"},
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError, ValueError):
        logger.info("Falha ao consultar última release no GitHub (best-effort)", exc_info=True)
        return None
    tag = payload.get("tag_name")
    if not tag:
        return None
    return {"tag": tag, "url": payload.get("html_url") or RELEASES_PAGE_URL}
