"""Extrai os sons que faltam em assets/mascot/<Nome>/sounds/*.wav a partir
da fonte original do clippy.js (clippy.js/agents/<Nome>/sounds-mp3.js) —
cada arquivo é um dicionário {id: "data:audio/mpeg;base64,..."} (sintaxe de
objeto JS, aspas simples, por isso ast.literal_eval em vez de json.loads).

Só extrai o que falta (nunca sobrescreve um .wav já existente) e só os ids
que status_animations["idle"/"working"/"error"] mais entrada/saída/alívio
realmente usam — não precisa converter o pacote inteiro de cada personagem.

Requer ffmpeg (decodifica o mp3 embutido e grava .wav).

Uso: python3 scripts/import_mascot_sounds.py
"""
import ast
import base64
import json
import re
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLIPPY_SRC = ROOT / "clippy.js" / "agents"
MASCOT_DIR = ROOT / "assets" / "mascot"

READY_RE = re.compile(r"^clippy\.soundsReady\('([^']+)',\s*(.*)\)\s*;?\s*$", re.S)

# mesma lista de nomes reservados de entrada/saída/alívio que
# import_mascot_agents.py usa — não estão em status_animations mas o motor
# também os toca.
EXTRA_NAMES = ("Show", "Hide", "HideQuick", "Greeting", "Greet", "Goodbye", "GoodBye", "Congratulate")


def _parse_sounds_js(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8").strip()
    match = READY_RE.match(text)
    if not match:
        raise ValueError(f"formato inesperado em {path}")
    return ast.literal_eval(match.group(2))


def _used_sound_ids(agent_data: dict) -> set[str]:
    used_anims = set(EXTRA_NAMES)
    for bucket in agent_data["status_animations"].values():
        used_anims.update(bucket)
    ids = set()
    for name in used_anims:
        anim = agent_data["animations"].get(name)
        if not anim:
            continue
        for frame in anim["frames"]:
            sound = frame.get("sound")
            if sound:
                ids.add(sound)
    return ids


def _decode_to_wav(data_uri: str, dest: Path) -> None:
    header, b64 = data_uri.split(",", 1)
    raw = base64.b64decode(b64)
    suffix = ".ogg" if "ogg" in header else ".mp3"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as tmp:
        tmp.write(raw)
        tmp.flush()
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", tmp.name, str(dest)],
            check=True,
        )


def main() -> None:
    for src_dir in sorted(CLIPPY_SRC.iterdir()):
        if not src_dir.is_dir():
            continue
        name = src_dir.name
        agent_json = MASCOT_DIR / name / "agent.json"
        sounds_js = src_dir / "sounds-mp3.js"
        if not agent_json.exists() or not sounds_js.exists():
            continue

        agent_data = json.loads(agent_json.read_text(encoding="utf-8"))
        needed = _used_sound_ids(agent_data)
        sounds_dir = MASCOT_DIR / name / "sounds"
        sounds_dir.mkdir(exist_ok=True)
        have = {p.stem for p in sounds_dir.glob("*.wav")}
        missing = sorted(needed - have)
        if not missing:
            print(f"{name}: nada faltando ({len(needed)} sons usados, todos presentes)")
            continue

        sound_data = _parse_sounds_js(sounds_js)
        extracted = 0
        skipped = []
        for sound_id in missing:
            data_uri = sound_data.get(sound_id)
            if not data_uri:
                skipped.append(sound_id)
                continue
            _decode_to_wav(data_uri, sounds_dir / f"{sound_id}.wav")
            extracted += 1
        msg = f"{name}: extraídos {extracted}/{len(missing)}"
        if skipped:
            msg += f" (sem dado na fonte: {skipped})"
        print(msg)


if __name__ == "__main__":
    main()
