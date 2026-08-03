"""Backend Windows (ConPTY via pywinpty) da sessão de terminal usada por
account_usage.py.

⚠️ AVISO PRA QUEM (OU QUAL CLAUDE) FOR MEXER NISSO NO WINDOWS ⚠️
Este arquivo NUNCA rodou de verdade — foi escrito só com base na documentação
do pywinpty, sem acesso a uma máquina Windows pra testar. `pty_session_posix.py`
(o equivalente Linux) foi testado rodando `python3 account_usage.py` direto e
recebendo a cota real de volta; este aqui não passou por isso ainda.

Se você é um Claude Code rodando numa máquina Windows e chegou aqui: por favor
teste antes de confiar neste código. Passos sugeridos:
1. `pip install pywinpty` (ou via requirements.txt do projeto, que já lista
   `pywinpty>=2.0; sys_platform == "win32"`).
2. Rodar `python account_usage.py` direto (tem `claude` no PATH) e comparar o
   dict devolvido com o que a tela `/usage` mostra manualmente no CLI.
3. Prestar atenção especial nestes pontos, que são os mais prováveis de
   quebrar por divergência de versão/API do pywinpty:
   - `winpty.PtyProcess.spawn(argv, cwd=..., env=...)` — confirmar que essa
     assinatura existe na versão instalada (pode variar entre major versions
     do pywinpty).
   - `.read(size)` devolvendo `str` já decodificado (não `bytes`) — se a
     versão instalada devolver bytes, `_pump`/`stream.feed` abaixo quebram.
   - `.write(str)` — mesma coisa, checar se espera `str` ou `bytes`.
   - `.isalive()` e `.terminate(force=True)` — confirmar que existem com essa
     assinatura.
4. Se algo divergir, ajuste só este arquivo — `account_usage.py` e
   `pty_session_posix.py` não devem precisar mudar, pois o contrato entre
   `fetch_account_usage()` e a classe de sessão (`write`/`read_into`/
   `terminate`) já foi desenhado pra ser idêntico entre os dois backends.

Depende do pacote pip "pywinpty" (import name "winpty"), que expõe
`winpty.PtyProcess`, uma classe que espelha de propósito a API de
`ptyprocess.PtyProcess` (mesmo padrão que o terminado do Jupyter usa pra ter
um único caminho de código POSIX/Windows) — `.spawn()`, `.read()`, `.write()`,
`.isalive()`, `.terminate()`.

`winpty.PtyProcess.read()` é bloqueante e sem parâmetro de timeout, diferente
do `select()` usado no backend POSIX (pty_session_posix.py) — por isso a
leitura roda numa thread separada que empurra os chunks numa fila, e
`read_into` consome essa fila com timeout, preservando o mesmo contrato
(devolve depois de N segundos, mesmo sem dado novo) que account_usage.py
espera do backend.
"""
import os
import queue
import threading
import time
from pathlib import Path

import winpty


class PtySessionWindows:
    def __init__(self, argv: list[str], cwd: Path, extra_env: dict[str, str]) -> None:
        env = os.environ.copy()
        env.update(extra_env)
        self._proc = winpty.PtyProcess.spawn(argv, cwd=str(cwd), env=env)
        self._queue: "queue.Queue[str | None]" = queue.Queue()
        self._reader = threading.Thread(target=self._pump, daemon=True)
        self._reader.start()

    def _pump(self) -> None:
        try:
            while True:
                chunk = self._proc.read(65536)
                if not chunk:
                    break
                self._queue.put(chunk)
        except EOFError:
            pass
        finally:
            self._queue.put(None)  # sentinela: pty fechado

    def write(self, data: bytes) -> None:
        self._proc.write(data.decode("utf-8", errors="ignore"))

    def read_into(self, stream: "pyte.Stream", seconds: float) -> None:  # noqa: F821
        deadline = time.time() + seconds
        while time.time() < deadline:
            remaining = deadline - time.time()
            try:
                chunk = self._queue.get(timeout=max(remaining, 0))
            except queue.Empty:
                continue
            if chunk is None:
                return  # pty fechado (processo filho morreu)
            stream.feed(chunk)

    def terminate(self, wait_seconds: float) -> None:
        try:
            self._proc.write("\x03\x03")  # Ctrl+C duas vezes: saida normal do Claude Code
        except (OSError, EOFError):
            pass
        deadline = time.time() + wait_seconds
        while time.time() < deadline and self._proc.isalive():
            time.sleep(0.1)
        if self._proc.isalive():
            self._proc.terminate(force=True)
