"""Reimporta assets/mascot/<Nome>/agent.json a partir da fonte original do
clippy.js (clippy.js/agents/<Nome>/agent.js), preservando branching,
exitBranch, useExitBranching e frames com múltiplas imagens compostas —
tudo que a conversão anterior tinha descartado (ver mascot.py para o motor
que agora sabe interpretar isso).

status_animations não existe nos dados do clippy.js (é curadoria nossa, pra
saber qual animação usar pra idle/working/error); é sempre recalculado a
partir das animações que o personagem realmente tem (idle: auto-detectado
por nome "Idle*"; working/error: ver DEFAULT_WORKING/DEFAULT_ERROR abaixo) —
rodar de novo nunca deixa curadoria antiga presa num personagem.

Uso: python3 scripts/import_mascot_agents.py
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLIPPY_SRC = ROOT / "clippy.js" / "agents"
MASCOT_DIR = ROOT / "assets" / "mascot"

# candidatas de status: idle é auto-detectado a partir dos nomes "Idle*"
# (como o próprio motor original faz em _getIdleAnimation); working e error
# usam TODO o repertório de gestos de cada personagem, exceto o que está
# reservado pra outra coisa (entrada/saída/alívio) ou depende de posição de
# mouse que não temos (Look/Gesture/Move/Hearing, e os fragmentos
# "Continued"/"Return" que só fazem sentido encadeados a um gesto assim).
RESERVED_NAMES = {
    "Show", "Hide", "HideQuick", "Greeting", "Greet", "Goodbye", "GoodBye",
    "Congratulate", "Congratulate_2",
    "RestPose",  # pose neutra estática — não é "fazendo algo", nem o motor original a inclui em idle/gestos
}
INTERACTIVE_PREFIXES = ("Look", "Gesture", "Move", "Hearing")
INTERACTIVE_NAMES = {"StartListening", "StopListening", "ClickedOn"}
INTERACTIVE_SUFFIXES = ("Continued", "Return")

# gestos de "aflição"/chamar atenção — o resto do repertório vira working.
ERROR_NAMES = [
    "Alert", "GetAttention", "GetAttention2", "GetAttentionMinor",
    "Surprised", "Embarrassed", "Confused", "Sad", "Uncertain", "Decline", "DontRecognize",
]

READY_RE = re.compile(r"^clippy\.ready\('([^']+)',\s*(.*)\)\s*;?\s*$", re.S)


def _parse_agent_js(path: Path) -> dict:
    text = path.read_text(encoding="utf-8").strip()
    match = READY_RE.match(text)
    if not match:
        raise ValueError(f"formato inesperado em {path}")
    return json.loads(match.group(2))


def _idle_names(animations: dict) -> list[str]:
    # "Idle" em qualquer parte do nome, não só no início — pega variantes
    # como DeepIdle1 (Genius/Rocky) e DeepIdleA/E (Links) que o próprio
    # motor original não tem um mecanismo de detecção pra alcançar (ele só
    # olha nomes com "Idle" no começo), mas que claramente são gestos de
    # ócio e não deveriam sobrar soltos no balaio do working.
    return sorted(name for name in animations if "Idle" in name)


def _is_interactive(name: str) -> bool:
    return (
        name.startswith(INTERACTIVE_PREFIXES)
        or name in INTERACTIVE_NAMES
        or name.endswith(INTERACTIVE_SUFFIXES)
    )


def _error_candidates(animations: dict) -> list[str]:
    return [name for name in ERROR_NAMES if name in animations]


def _working_candidates(animations: dict, error_names: list[str]) -> list[str]:
    reserved = RESERVED_NAMES | set(error_names)
    return sorted(
        name
        for name in animations
        if name not in reserved
        and "Idle" not in name
        and not _is_interactive(name)
    )


def main() -> None:
    for src_dir in sorted(CLIPPY_SRC.iterdir()):
        if not src_dir.is_dir():
            continue
        agent_js = src_dir / "agent.js"
        if not agent_js.exists():
            continue

        name = src_dir.name
        dest_dir = MASCOT_DIR / name
        dest_path = dest_dir / "agent.json"
        if not dest_dir.is_dir():
            print(f"pulando {name}: sem pasta em assets/mascot/")
            continue

        data = _parse_agent_js(agent_js)
        animations = data["animations"]

        error_candidates = _error_candidates(animations)
        status_animations = {
            "idle": _idle_names(animations),
            "working": _working_candidates(animations, error_candidates),
            "error": error_candidates,
        }

        out = {
            "overlayCount": data.get("overlayCount", 1),
            "sounds": data.get("sounds", []),
            "framesize": data["framesize"],
            "animations": animations,
            "status_animations": status_animations,
        }
        dest_path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        idle_n = len(status_animations["idle"])
        working_n = len(status_animations["working"])
        error_n = len(status_animations["error"])
        print(f"{name}: {len(animations)} animações totais — idle={idle_n} working={working_n} error={error_n}")


if __name__ == "__main__":
    main()
