"""Gera o som de alerta do Semáforo (assets/alert.wav): um arpejo curto de 3
notas com timbre de sino (fundamental + harmônico + decaimento exponencial),
em vez de um beep quadrado. Só usa a stdlib (módulo wave), sem dependências.

Rode de novo se quiser ajustar as notas/duração — o resultado é commitável
(o áudio final, não precisa rodar isso em cada máquina).

Uso: python3 generate_alert_sound.py
"""
import math
import struct
import wave
from pathlib import Path

SAMPLE_RATE = 44100
NOTES_HZ = (523.25, 659.25, 783.99)  # C5, E5, G5 — arpejo maior, soa "de aviso" mas agradável
NOTE_SECONDS = 0.16
GAP_SECONDS = 0.02
DECAY = 9.0  # quanto maior, mais rápido a nota "morre" (efeito sino)
OUTPUT = Path(__file__).resolve().parent / "assets" / "alert.wav"


def _note_samples(freq: float, duration: float) -> list[float]:
    n = int(SAMPLE_RATE * duration)
    samples = []
    for i in range(n):
        t = i / SAMPLE_RATE
        envelope = math.exp(-DECAY * t)
        fundamental = math.sin(2 * math.pi * freq * t)
        harmonic = 0.35 * math.sin(2 * math.pi * freq * 2 * t)  # 1ª oitava acima, mais fraco -> timbre de sino
        samples.append(envelope * (fundamental + harmonic))
    return samples


def _silence_samples(duration: float) -> list[float]:
    return [0.0] * int(SAMPLE_RATE * duration)


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    all_samples: list[float] = []
    for i, freq in enumerate(NOTES_HZ):
        all_samples.extend(_note_samples(freq, NOTE_SECONDS))
        if i < len(NOTES_HZ) - 1:
            all_samples.extend(_silence_samples(GAP_SECONDS))

    peak = max(abs(s) for s in all_samples) or 1.0
    pcm = b"".join(struct.pack("<h", int(max(-1.0, min(1.0, s / peak)) * 32767)) for s in all_samples)

    with wave.open(str(OUTPUT), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(SAMPLE_RATE)
        wav_file.writeframes(pcm)

    print(f"Gerado: {OUTPUT} ({len(all_samples) / SAMPLE_RATE:.2f}s)")


if __name__ == "__main__":
    main()
