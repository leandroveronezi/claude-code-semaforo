"""Backend Windows (ConPTY via pywinpty) da sessão de terminal usada por
account_usage.py.

Validado de verdade numa máquina Windows (Windows 11, Python 3.14, pywinpty
3.0.5) rodando `python account_usage.py` e conferindo o resultado contra a tela
`/usage` do CLI — este arquivo já foi escrito uma vez só a partir da
documentação, sem execução real, e o que se aprendeu nessa validação está
registrado abaixo pra não se perder.

Depende do pacote pip "pywinpty" (import name "winpty"), que expõe
`winpty.PtyProcess`, uma classe que espelha de propósito a API de
`ptyprocess.PtyProcess` (mesmo padrão que o terminal do Jupyter usa pra ter
um único caminho de código POSIX/Windows) — `.spawn()`, `.read()`, `.write()`,
`.isalive()`, `.terminate()`.

O que a validação confirmou (pywinpty 3.0.5):
- `PtyProcess.spawn(argv, cwd=None, env=None, dimensions=(24, 80), backend=None)`
  existe com essa assinatura; `env` é um dict comum de str.
- `.read(size)` devolve `str` já decodificado e `.write(s)` espera `str`
  (não bytes) — daí o decode/encode nas bordas desta classe, que fala bytes
  pra fora igual ao backend POSIX.
- `.isalive()` e `.terminate(force=True)` existem e funcionam.

E a armadilha que a documentação NÃO conta, e que o `_pump` abaixo depende de
tratar certo: **`.read()` devolve string vazia (`''`) o tempo todo enquanto o
pty está ocioso, e isso NÃO é EOF.** A thread interna do pywinpty manda um
sentinela `b'0011Ignore'` sempre que a leitura de baixo nível volta vazia
(ver `_read_in_thread` em winpty/ptyprocess.py), e `PtyProcess.read()`
converte esse sentinela em `''` antes de devolver. Só `EOFError` significa pty
fechado. Um `if not chunk: break` no laço de leitura — que é o idiomático em
qualquer outro pty — encerra a leitura no primeiro instante de ociosidade e faz
a consulta inteira devolver vazio.

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

# ConPTY exige um tamanho explícito, mas o backend POSIX não passa nenhum:
# `pty.fork()` nasce com winsize 0x0 e o Ink (TUI do Claude Code) cai no
# fallback 80x24. Replicamos esse mesmo tamanho aqui pra a tela do /usage sair
# com o layout que os regexes de account_usage.py já foram ajustados pra ler.
# É de propósito que isso NÃO seja o tamanho do pyte.Screen (200x50): a tela
# renderiza mais estreita que o buffer, o que é inofensivo, enquanto um
# terminal largo demais faria o CLI escolher outro layout.
DIMENSIONS = (24, 80)  # (linhas, colunas), na ordem que o pywinpty espera

# shims de instalação via npm são batch (.cmd/.bat), que CreateProcess — usado
# pelo ConPTY por baixo — não executa direto; precisam do interpretador.
_BATCH_SUFFIXES = (".cmd", ".bat")


class PtySessionWindows:
    def __init__(self, argv: list[str], cwd: Path, extra_env: dict[str, str]) -> None:
        env = os.environ.copy()
        env.update(extra_env)
        if Path(argv[0]).suffix.lower() in _BATCH_SUFFIXES:
            argv = ["cmd.exe", "/c", *argv]
        self._proc = winpty.PtyProcess.spawn(
            argv, cwd=str(cwd), env=env, dimensions=DIMENSIONS
        )
        self._queue: "queue.Queue[str | None]" = queue.Queue()
        self._reader = threading.Thread(target=self._pump, daemon=True)
        self._reader.start()

    def _pump(self) -> None:
        try:
            while True:
                chunk = self._proc.read(65536)
                # '' é o sentinela de "nada disponível agora" do pywinpty, não
                # EOF (ver cabeçalho) — só o EOFError abaixo encerra a leitura.
                if chunk:
                    self._queue.put(chunk)
        except EOFError:
            pass
        except Exception:
            # o módulo nativo (_winpty) levanta WinptyError, que não é OSError;
            # sem este catch a thread daemon morreria calada e todo read_into
            # seguinte queimaria o timeout inteiro sem nenhum diagnóstico.
            pass
        finally:
            self._queue.put(None)  # sentinela: pty fechado

    def write(self, data: bytes) -> None:
        try:
            self._proc.write(data.decode("utf-8", errors="ignore"))
        except EOFError as exc:
            # o backend POSIX (os.write) sinaliza pty morto com OSError, e é
            # isso que fetch_account_usage() trata — traduz aqui pra manter os
            # dois backends com o mesmo contrato de exceção.
            raise OSError("pty fechado") from exc

    def read_into(self, stream: "pyte.Stream", seconds: float) -> None:  # noqa: F821
        deadline = time.time() + seconds
        while time.time() < deadline:
            remaining = deadline - time.time()
            try:
                chunk = self._queue.get(timeout=max(remaining, 0))
            except queue.Empty:
                continue
            if chunk is None:
                # devolve a sentinela: fetch_account_usage() chama read_into
                # várias vezes, e sem isso só a primeira chamada perceberia o
                # pty fechado — as seguintes esperariam o timeout inteiro à toa.
                self._queue.put(None)
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
        try:
            if self._proc.isalive():
                self._proc.terminate(force=True)
            # cada PtyProcess abre um socket de loopback e sobe uma thread
            # própria pra bombear a leitura (ver __init__ do pywinpty); sem o
            # close() explícito isso só seria liberado quando o GC recolhesse o
            # objeto, acumulando a cada consulta (uma a cada ~20min).
            self._proc.close(force=True)
        except (OSError, EOFError):
            pass
