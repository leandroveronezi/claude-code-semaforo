"""Backend POSIX (pty.fork) da sessão de terminal usada por account_usage.py.

Só é importado quando account_usage.IS_WINDOWS é False — o resto do arquivo
(parsing da tela, cache, timings) é compartilhado e vive em account_usage.py;
aqui fica só o "abrir claude num pseudo-terminal e ler/escrever nele".
"""
import os
import pty
import select
import signal
import time
from pathlib import Path


class PtySessionPosix:
    def __init__(self, argv: list[str], cwd: Path, extra_env: dict[str, str]) -> None:
        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            os.chdir(cwd)
            os.environ.update(extra_env)
            try:
                os.execv(argv[0], argv)
            except OSError:
                os._exit(1)

    def write(self, data: bytes) -> None:
        os.write(self.fd, data)

    def read_into(self, stream: "pyte.Stream", seconds: float) -> None:  # noqa: F821
        deadline = time.time() + seconds
        while time.time() < deadline:
            remaining = deadline - time.time()
            ready, _, _ = select.select([self.fd], [], [], max(remaining, 0))
            if self.fd not in ready:
                continue
            try:
                chunk = os.read(self.fd, 65536)
            except OSError:
                return  # pty fechado (processo filho morreu)
            if not chunk:
                return
            stream.feed(chunk.decode(errors="ignore"))

    def terminate(self, wait_seconds: float) -> None:
        try:
            os.write(self.fd, b"\x03\x03")  # Ctrl+C duas vezes: saida normal do Claude Code
        except OSError:
            pass
        deadline = time.time() + wait_seconds
        while time.time() < deadline:
            try:
                done_pid, _ = os.waitpid(self.pid, os.WNOHANG)
            except ChildProcessError:
                break
            if done_pid == self.pid:
                break
            time.sleep(0.1)
        else:
            try:
                os.kill(self.pid, signal.SIGKILL)
                os.waitpid(self.pid, 0)
            except (OSError, ChildProcessError):
                pass
        try:
            os.close(self.fd)
        except OSError:
            pass
