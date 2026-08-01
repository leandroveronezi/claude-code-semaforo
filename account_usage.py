"""Coleta best-effort da cota agregada da conta (uso do plano Pro/Max, janelas
de 5h e 7 dias) exibida em `/usage` dentro do próprio Claude Code CLI.

Não existe hook, arquivo local nem API pública para esse número — é dado
exclusivo da tela interativa do CLI (confirmado via strings do binário: o
próprio `claude` busca isso de um endpoint OAuth interno não documentado, e
optamos por não reimplementar isso lidando com credenciais alheias). Em vez
disso, automatizamos a própria tela: abrimos um `claude` real num
pseudo-terminal, digitamos `/usage` e usamos `pyte` (emulador de terminal)
para renderizar e ler o texto da tela — o mesmo que um humano veria.

Efeitos colaterais evitados deliberadamente:
- `SEMAFORO_SKIP_HOOK=1` no ambiente do processo filho, checado em
  hooks/status_hook.py, pra essa sessão automatizada não aparecer como uma
  sessão fantasma no painel.
- `--session-id` fixo + limpeza do .jsonl correspondente ao final, pra não
  poluir o histórico/`/resume` do usuário com dezenas de sessões vazias.
"""
import json
import os
import pty
import re
import select
import shutil
import signal
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pyte

PROJECT_DIR = Path(__file__).resolve().parent
CLAUDE_BIN_FALLBACK = Path.home() / ".local" / "bin" / "claude"
# último resultado bem-sucedido, pra mostrar algo de imediato ao abrir o app
# em vez de deixar a caixa sumida pelos ~5-30s até a primeira consulta real
# terminar (fetch_account_usage é lento — ver comentário da função). Puramente
# best-effort: se o arquivo não existir ou vier corrompido, o app segue sem
# cache nenhum, igual antes.
CACHE_PATH = Path.home() / ".config" / "semaforo-status" / "account_usage_cache.json"
# fixo (uuid5 determinístico) pra sempre reaproveitar/limpar o mesmo arquivo
# de sessão em vez de acumular um novo a cada consulta.
FIXED_SESSION_ID = str(uuid.uuid5(uuid.NAMESPACE_DNS, "semaforo-status.account-usage"))

COLS, ROWS = 200, 50
STARTUP_WAIT_SECONDS = 6
TRUST_DIALOG_WAIT_SECONDS = 2
USAGE_SCREEN_WAIT_SECONDS = 5
# teto de espera adicional (além do USAGE_SCREEN_WAIT_SECONDS inicial) caso o
# bloco "Current session" ainda não tenha terminado de carregar — ver loop de
# retry em fetch_account_usage().
USAGE_SCREEN_MAX_EXTRA_WAIT_SECONDS = 8
USAGE_SCREEN_POLL_INTERVAL_SECONDS = 1
GRACEFUL_EXIT_WAIT_SECONDS = 1.5

# o "% used" da janela de sessão às vezes não termina de carregar a tempo do
# nosso timeout inicial (a de semana parece vir de um valor já em cache, mais
# rápido) — por isso os dois blocos são casados e são opcionais separadamente,
# em vez de um único regex que falharia por completo se faltasse só um dos
# dois, e fetch_account_usage() continua tentando ler um pouco mais enquanto
# só a sessão estiver faltando.
# layout da tela (barra + "NN% used" numa linha, "Resets ..." na linha
# seguinte — mudou de ordem numa atualização do CLI, era tudo numa linha só
# antes). [^\n]* em vez de .* (mesmo sem re.S) pra "pct" e "resets" ficarem
# restritos aos dois-linhas do próprio bloco, sem vazar pro bloco seguinte
# quando o "% used" da sessão não veio (caso do throttling acima) — nesse
# caso o regex simplesmente não casa, em vez de casar errado com a semana.
SESSION_RE = re.compile(r"Current session\s*\n[^\n]*?(?P<pct>\d+)% used\s*\n\s*Resets (?P<resets>[^\n]+)")
WEEK_RE = re.compile(r"Current week.*\n[^\n]*?(?P<pct>\d+)% used\s*\n\s*Resets (?P<resets>[^\n]+)")

# extrai a timezone entre parênteses no final do texto de reset (ex.:
# "10:10pm (America/Campo_Grande)", "Aug 4, 12pm (America/Campo_Grande)") —
# é sempre o último parêntese da string, então buscar a partir do fim evita
# qualquer ambiguidade com outros parênteses que a tela venha a ter.
_RESET_TZ_RE = re.compile(r"\(([^)]+)\)\s*$")
# ordem importa: tenta primeiro com data (semana), depois só hora (sessão);
# dentro de cada um, tenta com minutos antes de sem minutos ("12pm" sem :00).
_RESET_TIME_FORMATS = (
    ("%b %d, %I:%M%p", True),
    ("%b %d, %I%p", True),
    ("%I:%M%p", False),
    ("%I%p", False),
)


def load_cached_usage() -> dict | None:
    try:
        return json.loads(CACHE_PATH.read_text())
    except (OSError, ValueError):
        return None


def save_cached_usage(data: dict) -> None:
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps(data))
    except OSError:
        pass


def _claude_bin() -> str | None:
    found = shutil.which("claude")
    if found:
        return found
    # autostart (freedesktop) roda com PATH mínimo, sem ~/.local/bin
    return str(CLAUDE_BIN_FALLBACK) if CLAUDE_BIN_FALLBACK.exists() else None


def _project_hash_dir() -> Path:
    return Path.home() / ".claude" / "projects" / str(PROJECT_DIR).replace("/", "-")


def _cleanup_session_file() -> None:
    directory = _project_hash_dir()
    session_file = directory / f"{FIXED_SESSION_ID}.jsonl"
    session_file.unlink(missing_ok=True)
    session_extra_dir = directory / FIXED_SESSION_ID
    if session_extra_dir.is_dir():
        shutil.rmtree(session_extra_dir, ignore_errors=True)


def _read_into(fd: int, stream: "pyte.Stream", seconds: float) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        remaining = deadline - time.time()
        ready, _, _ = select.select([fd], [], [], max(remaining, 0))
        if fd not in ready:
            continue
        try:
            chunk = os.read(fd, 65536)
        except OSError:
            return  # pty fechado (processo filho morreu)
        if not chunk:
            return
        stream.feed(chunk.decode(errors="ignore"))


def _parse_usage_screen(text: str) -> dict | None:
    session_match = SESSION_RE.search(text)
    week_match = WEEK_RE.search(text)
    if not session_match and not week_match:
        return None
    result = {"fetched_at": time.time()}
    if session_match:
        result["session_pct"] = int(session_match["pct"])
        result["session_resets"] = session_match["resets"].strip()
    if week_match:
        result["week_pct"] = int(week_match["pct"])
        result["week_resets"] = week_match["resets"].strip()
    return result


def parse_reset_datetime(reset_text: str, now: datetime | None = None) -> datetime | None:
    """Converte o texto livre de "Resets ..." (ex.: "10:10pm
    (America/Campo_Grande)", sem data — reseta na janela de 5h; ou "Aug 4,
    12pm (America/Campo_Grande)", com data — reseta na janela de 7 dias) no
    datetime absoluto mais próximo no futuro. None se não conseguir
    interpretar (formato mudou, tz desconhecida etc.) — best-effort, quem
    chama deve tratar como "não sabemos quando reseta" em vez de travar
    nisso."""
    tz_match = _RESET_TZ_RE.search(reset_text)
    if not tz_match:
        return None
    try:
        tz = ZoneInfo(tz_match.group(1).strip())
    except (KeyError, ValueError):
        return None
    body = reset_text[: tz_match.start()].strip()
    now = now.astimezone(tz) if now else datetime.now(tz)

    for fmt, has_date in _RESET_TIME_FORMATS:
        try:
            parsed = datetime.strptime(body, fmt)
        except ValueError:
            continue
        if has_date:
            # sem ano no texto: assume o ano corrente, e só empurra pro
            # próximo ano se isso colocar a data claramente no passado (a
            # janela de 7 dias nunca reseta a mais de 7 dias daqui).
            result = parsed.replace(year=now.year, tzinfo=tz)
            if result < now - timedelta(days=1):
                result = result.replace(year=now.year + 1)
        else:
            result = now.replace(hour=parsed.hour, minute=parsed.minute, second=0, microsecond=0)
            if result <= now:
                result += timedelta(days=1)
        return result
    return None


def fetch_account_usage() -> dict | None:
    """Roda o fluxo completo num processo filho descartável. Devolve None em
    qualquer falha (binário ausente, timeout, tela em formato inesperado) —
    é sempre best-effort, nunca deve derrubar quem chamou."""
    claude_bin = _claude_bin()
    if claude_bin is None:
        return None

    screen = pyte.Screen(COLS, ROWS)
    stream = pyte.Stream(screen)

    pid, fd = pty.fork()
    if pid == 0:
        os.chdir(PROJECT_DIR)
        os.environ["SEMAFORO_SKIP_HOOK"] = "1"
        try:
            os.execv(claude_bin, [claude_bin, "--session-id", FIXED_SESSION_ID, "--strict-mcp-config"])
        except OSError:
            os._exit(1)

    try:
        _read_into(fd, stream, STARTUP_WAIT_SECONDS)
        os.write(fd, b"\r")  # aceita o dialogo de confianca da pasta, se aparecer; inofensivo se ja estiver no prompt
        _read_into(fd, stream, TRUST_DIALOG_WAIT_SECONDS)
        os.write(fd, b"/usage\r")
        _read_into(fd, stream, USAGE_SCREEN_WAIT_SECONDS)
        result = _parse_usage_screen("\n".join(screen.display))
        # sessão ainda não veio: insiste um pouco mais em vez de devolver logo
        # o parcial só-com-semana (ver comentário de SESSION_RE/WEEK_RE acima).
        deadline = time.time() + USAGE_SCREEN_MAX_EXTRA_WAIT_SECONDS
        while (not result or "session_pct" not in result) and time.time() < deadline:
            _read_into(fd, stream, USAGE_SCREEN_POLL_INTERVAL_SECONDS)
            result = _parse_usage_screen("\n".join(screen.display))
        return result
    except OSError:
        return None
    finally:
        _terminate(pid, fd)
        _cleanup_session_file()


def _terminate(pid: int, fd: int) -> None:
    try:
        os.write(fd, b"\x03\x03")  # Ctrl+C duas vezes: saida normal do Claude Code
    except OSError:
        pass
    deadline = time.time() + GRACEFUL_EXIT_WAIT_SECONDS
    while time.time() < deadline:
        try:
            done_pid, _ = os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            break
        if done_pid == pid:
            break
        time.sleep(0.1)
    else:
        try:
            os.kill(pid, signal.SIGKILL)
            os.waitpid(pid, 0)
        except (OSError, ChildProcessError):
            pass
    try:
        os.close(fd)
    except OSError:
        pass


if __name__ == "__main__":
    print(fetch_account_usage())
