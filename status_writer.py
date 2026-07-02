"""CLI para atualizar o status de uma sessão (um editor/agente/aba).

Uso:
    python status_writer.py <session_id> <idle|working|error> [--label "Nome"]

Pensado para ser chamado a partir de hooks do Claude Code, do VSCode ou de
qualquer outro processo que precise reportar seu estado ao semáforo.
"""
import argparse

from status_store import STATUSES, write_status


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session_id", help="Identificador único da sessão (ex.: nome da janela/aba)")
    parser.add_argument("status", choices=STATUSES, help="idle=verde, working=amarelo, error=vermelho")
    parser.add_argument("--label", help="Texto exibido no semáforo (padrão: o próprio session_id)")
    args = parser.parse_args()

    path = write_status(args.session_id, args.status, args.label)
    print(f"status de '{args.session_id}' -> {args.status} ({path})")


if __name__ == "__main__":
    main()
