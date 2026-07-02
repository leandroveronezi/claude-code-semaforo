"""Simulador de demonstração: cria 3 sessões (como se fossem 3 editores/abas
diferentes) e alterna seus status aleatoriamente, para ver vários semáforos
na tela ao mesmo tempo sem precisar plugar um agente de verdade."""
import random
import time

from status_store import write_status

SESSIONS = [
    ("editor-1", "VSCode — projeto A"),
    ("editor-2", "VSCode — projeto B (aba 2)"),
    ("editor-3", "VSCode — projeto C"),
]

# idle é o mais comum, error é raro
WEIGHTED_STATUSES = ["idle"] * 5 + ["working"] * 4 + ["error"] * 1


def main() -> None:
    for session_id, label in SESSIONS:
        write_status(session_id, "idle", label)

    print("Simulando 3 sessões. Ctrl+C para parar.")
    try:
        while True:
            session_id, label = random.choice(SESSIONS)
            status = random.choice(WEIGHTED_STATUSES)
            write_status(session_id, status, label)
            print(f"{label} -> {status}")
            time.sleep(random.uniform(1.5, 4.0))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
