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
import re
import shutil
import sys
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pyte

from logging_setup import setup_logging

logger = setup_logging("semaforo", "semaforo.log")

# Abrir claude num pseudo-terminal exige um backend por SO (pty.fork no
# POSIX, ConPTY via pywinpty no Windows) — ver pty_session_posix.py /
# pty_session_windows.py. O backend em si só é importado dentro de
# fetch_account_usage(), nunca aqui no topo do módulo: session_manager.py
# importa account_usage no nível de módulo, então um import incondicional do
# backend errado (ou de uma dependência ausente, como pywinpty não instalado)
# derrubaria o app inteiro em vez de só desabilitar essa consulta.
IS_WINDOWS = sys.platform == "win32"

PROJECT_DIR = Path(__file__).resolve().parent
CLAUDE_BIN_FALLBACK = Path.home() / ".local" / "bin" / "claude"
# config global do CLI (não é por-sessão) — todo `claude` que sobe, inclusive
# a sessão descartável daqui, lê/mescla/regrava esse arquivo inteiro. Rede de
# segurança em _backup_claude_config/_restore_claude_config_if_corrupted: se o
# processo descartável for morto (SIGKILL, ver GRACEFUL_EXIT_WAIT_SECONDS) no
# meio de uma escrita, o arquivo pode truncar — e como é lido por *todo*
# `claude` subsequente, um `.claude.json` corrompido quebraria o CLI de
# verdade do usuário, não só essa consulta de cota. Não tenta resolver a
# corrida de "última escrita ganha" entre a sessão descartável e uma sessão
# interativa concorrente (só restaura se o arquivo ficou inválido, nunca por
# ele só ter mudado de conteúdo) — isso exigiria entender o formato interno
# do CLI, que é fechado.
CLAUDE_CONFIG_PATH = Path.home() / ".claude.json"
# trava pra impedir duas consultas de cota concorrentes entre *processos*
# diferentes (ex.: `python3 account_usage.py` manual enquanto o app já está
# de pé, ou duas instâncias do app — ver SEMAFORO_STATUS_DIR). O guard em
# SessionManager._poll_account_usage só cobre sobreposição dentro do mesmo
# processo; sem essa trava, dois processos sobem o mesmo --session-id fixo em
# paralelo e disputam o mesmo ~/.claude.json — já observado corrompendo de
# verdade em teste manual (ver _backup_claude_config acima).
ACCOUNT_USAGE_LOCK_PATH = Path.home() / ".config" / "semaforo-status" / "account_usage.lock"
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
# telas do onboarding de primeira execução do CLI (escolha de tema, escolha de
# método de login). Não dá pra atravessá-las às cegas: o `\r` que aceita o
# diálogo de confiança viraria "selecionar a opção 1" no menu de login, o que
# dispara um fluxo OAuth de verdade (abre o navegador, fica esperando um código
# colado) em nome do usuário, sem ele ter pedido nada. Melhor reconhecer e
# desistir — só faz falta em máquina onde o `claude` nunca foi rodado como CLI
# (ex.: uso só pela extensão do VS Code), e uma execução manual resolve.
ONBOARDING_RE = re.compile(
    r"Choose the text style|Select login method|Paste code here if prompted"
)
SESSION_RE = re.compile(r"Current session\s*\n[^\n]*?(?P<pct>\d+)% used\s*\n\s*Resets (?P<resets>[^\n]+)")
WEEK_RE = re.compile(r"Current week.*\n[^\n]*?(?P<pct>\d+)% used\s*\n\s*Resets (?P<resets>[^\n]+)")

# extrai a timezone entre parênteses no final do texto de reset (ex.:
# "10:10pm (America/Campo_Grande)", "Aug 4, 12pm (America/Campo_Grande)") —
# é sempre o último parêntese da string, então buscar a partir do fim evita
# qualquer ambiguidade com outros parênteses que a tela venha a ter.
_RESET_TZ_RE = re.compile(r"\(([^)]+)\)\s*$")
# NÃO usar datetime.strptime com %b/%p aqui: os dois são sensíveis ao locale
# do processo (nomes de mês, designadores AM/PM), e o Qt muda o locale global
# (LC_TIME) pro do sistema assim que QApplication() é instanciado — em pt_BR
# isso quebra o parsing de "Aug"/"pm" de forma totalmente silenciosa
# (parse_reset_datetime só devolve None, sem erro nenhum). O texto vem sempre
# em inglês da própria tela do CLI, então parseamos à mão em vez de depender
# do locale do processo pra interpretá-lo.
_RESET_TIME_RE = re.compile(
    r"^(?:(?P<month>[A-Za-z]{3}) (?P<day>\d{1,2}), )?"
    r"(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?(?P<ampm>[AaPp][Mm])$"
)
_MONTH_ABBR = {
    name: i + 1
    for i, name in enumerate(
        ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
    )
}


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


def _vscode_extension_binaries() -> list[Path]:
    """Binário embutido na extensão do VS Code. É a única instalação presente
    em máquinas Windows onde o Claude Code só é usado pela IDE — nesse caso não
    existe `claude` no PATH nenhum, e sem este candidato a consulta de cota
    simplesmente nunca roda. Ordena por versão de verdade (tupla de inteiros,
    não string: "2.1.9" tem que perder pra "2.1.10")."""
    def version_key(path: Path) -> tuple[int, ...]:
        match = re.search(r"claude-code-(\d+(?:\.\d+)*)", path.name)
        return tuple(int(part) for part in match.group(1).split(".")) if match else ()

    found: list[Path] = []
    for root_name in (".vscode", ".vscode-insiders"):
        root = Path.home() / root_name / "extensions"
        found.extend(sorted(root.glob("anthropic.claude-code-*"), key=version_key, reverse=True))
    return [d / "resources" / "native-binary" / "claude.exe" for d in found]


def _claude_bin() -> str | None:
    found = shutil.which("claude")
    if found:
        return found
    if IS_WINDOWS:
        # o PATH do processo pode não ter o CLI (instalação só pela extensão do
        # VS Code, ou app subindo por atalho de inicialização) — mesma ideia do
        # CLAUDE_BIN_FALLBACK do POSIX, só que com mais de um lugar plausível.
        candidates = [Path.home() / ".local" / "bin" / "claude.exe"]
        appdata = os.environ.get("APPDATA")
        if appdata:
            candidates.append(Path(appdata) / "npm" / "claude.cmd")
        candidates.extend(_vscode_extension_binaries())
    else:
        # autostart (freedesktop) roda com PATH mínimo, sem ~/.local/bin
        candidates = [CLAUDE_BIN_FALLBACK]
    return next((str(path) for path in candidates if path.exists()), None)


def _project_hash_dirs() -> list[Path]:
    """Diretórios onde o Claude Code pode ter gravado o .jsonl da sessão
    descartável. Mais de um no Windows: o nome é derivado do cwd como string, e
    a caixa da letra do drive varia com quem lançou o processo (`Path.resolve()`
    devolve "C:", o VS Code passa "c:") — a limpeza tenta as duas em vez de
    apostar numa."""
    projects = Path.home() / ".claude" / "projects"
    if not IS_WINDOWS:
        return [projects / str(PROJECT_DIR).replace("/", "-")]
    # convenção do Claude Code no Windows: todo caractere não-alfanumérico
    # (inclusive "\" e ":") vira "-", ex.: "c--Users-henri-...-semaforo".
    raw = str(PROJECT_DIR)
    variants = {raw, raw[:1].lower() + raw[1:], raw[:1].upper() + raw[1:]}
    return [projects / re.sub(r"[^A-Za-z0-9]", "-", variant) for variant in variants]


def _try_acquire_account_usage_lock():
    """Tenta travar ACCOUNT_USAGE_LOCK_PATH sem bloquear. Devolve o file
    handle aberto (mantenha vivo até terminar) se conseguiu, ou None se outro
    processo já tem a trava — chamador deve desistir, nunca esperar (ver
    comentário de ACCOUNT_USAGE_LOCK_PATH acima).

    É uma trava do SO sobre o file descriptor (flock/LockFileEx), não um
    lockfile-com-pid: libera sozinha quando o processo termina, inclusive
    SIGKILL, sem lock obsoleto pra limpar manualmente depois de um crash."""
    ACCOUNT_USAGE_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    fh = open(ACCOUNT_USAGE_LOCK_PATH, "a+b")
    try:
        if IS_WINDOWS:
            import msvcrt
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return None
    return fh


def _release_account_usage_lock(fh) -> None:
    try:
        if IS_WINDOWS:
            import msvcrt
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass
    finally:
        fh.close()


def _backup_claude_config() -> bytes | None:
    try:
        return CLAUDE_CONFIG_PATH.read_bytes()
    except OSError:
        return None


def _restore_claude_config_if_corrupted(backup: bytes | None) -> None:
    """Só mexe no arquivo se ele ficou inválido (JSON quebrado/ilegível) após
    a sessão descartável — nunca por ter mudado de conteúdo, pra não apagar
    uma escrita legítima de uma sessão interativa concorrente (ver comentário
    de CLAUDE_CONFIG_PATH)."""
    if backup is None:
        return
    try:
        json.loads(CLAUDE_CONFIG_PATH.read_bytes())
        return  # ainda válido, nada a fazer
    except (OSError, ValueError):
        pass
    try:
        CLAUDE_CONFIG_PATH.write_bytes(backup)
        logger.warning(
            "~/.claude.json ficou corrompido logo após a consulta de cota; restaurado do backup "
            "feito antes de abrir a sessão descartável"
        )
    except OSError:
        logger.error("~/.claude.json corrompido e não foi possível restaurar o backup", exc_info=True)


def _cleanup_session_file() -> None:
    for directory in _project_hash_dirs():
        session_file = directory / f"{FIXED_SESSION_ID}.jsonl"
        session_file.unlink(missing_ok=True)
        session_extra_dir = directory / FIXED_SESSION_ID
        if session_extra_dir.is_dir():
            shutil.rmtree(session_extra_dir, ignore_errors=True)


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

    match = _RESET_TIME_RE.match(body)
    if not match:
        return None
    hour = int(match["hour"]) % 12
    if match["ampm"].lower() == "pm":
        hour += 12
    minute = int(match["minute"]) if match["minute"] else 0

    if match["month"]:
        month = _MONTH_ABBR.get(match["month"].lower())
        if month is None:
            return None
        # sem ano no texto: assume o ano corrente, e só empurra pro
        # próximo ano se isso colocar a data claramente no passado (a
        # janela de 7 dias nunca reseta a mais de 7 dias daqui).
        result = now.replace(
            year=now.year, month=month, day=int(match["day"]),
            hour=hour, minute=minute, second=0, microsecond=0,
        )
        if result < now - timedelta(days=1):
            result = result.replace(year=now.year + 1)
    else:
        result = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if result <= now:
            result += timedelta(days=1)
    return result


def _pty_session_class():
    """Import tardio e guardado do backend certo pro SO atual — nunca no topo
    do módulo (ver comentário de IS_WINDOWS acima). Devolve None se o backend
    não puder ser usado (ex.: pywinpty não instalado no Windows), caso em que
    fetch_account_usage() deve desistir sem quebrar."""
    if IS_WINDOWS:
        try:
            from pty_session_windows import PtySessionWindows
        except ImportError:
            logger.debug("pywinpty não instalado; pulando consulta de cota no Windows")
            return None
        return PtySessionWindows
    from pty_session_posix import PtySessionPosix
    return PtySessionPosix


def fetch_account_usage() -> dict | None:
    """Roda o fluxo completo num processo filho descartável. Devolve None em
    qualquer falha (binário ausente, timeout, tela em formato inesperado) —
    é sempre best-effort, nunca deve derrubar quem chamou."""
    session_cls = _pty_session_class()
    if session_cls is None:
        return None
    claude_bin = _claude_bin()
    if claude_bin is None:
        logger.debug("Binário 'claude' não encontrado; pulando consulta de cota")
        return None

    lock = _try_acquire_account_usage_lock()
    if lock is None:
        logger.debug("Outra consulta de cota já está em andamento em outro processo; pulando")
        return None

    try:
        screen = pyte.Screen(COLS, ROWS)
        stream = pyte.Stream(screen)
        config_backup = _backup_claude_config()

        # dentro do try: o spawn em si pode falhar (binário inválido, ConPTY
        # indisponível), e mesmo aí o `finally` precisa rodar a limpeza.
        session = None
        try:
            session = session_cls(
                [claude_bin, "--session-id", FIXED_SESSION_ID, "--strict-mcp-config"],
                PROJECT_DIR,
                {"SEMAFORO_SKIP_HOOK": "1"},
            )
            session.read_into(stream, STARTUP_WAIT_SECONDS)
            if ONBOARDING_RE.search("\n".join(screen.display)):
                logger.warning(
                    "O CLI 'claude' abriu no onboarding de primeira execução (tema/login) em vez "
                    "do prompt; rode 'claude' uma vez num terminal e conclua o fluxo. Pulando a "
                    "consulta de cota."
                )
                return None
            session.write(b"\r")  # aceita o dialogo de confianca da pasta, se aparecer; inofensivo se ja estiver no prompt
            session.read_into(stream, TRUST_DIALOG_WAIT_SECONDS)
            session.write(b"/usage\r")
            session.read_into(stream, USAGE_SCREEN_WAIT_SECONDS)
            result = _parse_usage_screen("\n".join(screen.display))
            # sessão ainda não veio: insiste um pouco mais em vez de devolver logo
            # o parcial só-com-semana (ver comentário de SESSION_RE/WEEK_RE acima).
            deadline = time.time() + USAGE_SCREEN_MAX_EXTRA_WAIT_SECONDS
            while (not result or "session_pct" not in result) and time.time() < deadline:
                session.read_into(stream, USAGE_SCREEN_POLL_INTERVAL_SECONDS)
                result = _parse_usage_screen("\n".join(screen.display))
            if not result:
                logger.warning("Tela de /usage não teve o formato esperado dentro do tempo limite")
            elif "session_pct" not in result:
                logger.debug("Consulta de cota voltou sem session_pct (throttling conhecido)")
            return result
        except OSError:
            logger.warning("Falha de E/S ao consultar cota da conta (pty)", exc_info=True)
            return None
        finally:
            if session is not None:
                session.terminate(GRACEFUL_EXIT_WAIT_SECONDS)
            _cleanup_session_file()
            _restore_claude_config_if_corrupted(config_backup)
    finally:
        _release_account_usage_lock(lock)


if __name__ == "__main__":
    print(fetch_account_usage())
