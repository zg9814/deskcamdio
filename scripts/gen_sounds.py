"""Generate placeholder UI sounds into assets/sounds (reproducible build step).

Real recordings can replace these files at any time; names must stay:
tap.ogg/wav, shutter, alarm, error.
"""

from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

RATE = 22050


def _write(path: Path, samples: list[float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = b"".join(struct.pack("<h", max(-32767, min(32767, int(s * 32767)))) for s in samples)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(RATE)
        handle.writeframes(pcm)


def sine(freq: float, seconds: float, gain: float = 0.6) -> list[float]:
    n = int(RATE * seconds)
    return [gain * math.sin(2 * math.pi * freq * i / RATE) * (1 - i / n) for i in range(n)]


def noise(seconds: float, gain: float = 0.5) -> list[float]:
    import random

    rng = random.Random(42)
    n = int(RATE * seconds)
    return [gain * (rng.random() * 2 - 1) * (1 - i / n) for i in range(n)]


def main() -> None:
    out = Path(__file__).resolve().parents[1] / "src" / "deskcamdio" / "assets" / "sounds"
    _write(out / "tap.wav", sine(1250, 0.05))
    _write(out / "shutter.wav", noise(0.09))
    alarm = sine(880, 0.14) + [0.0] * int(RATE * 0.02) + sine(1175, 0.14)
    _write(out / "alarm.wav", alarm)
    _write(
        out / "error.wav",
        [
            0.5 * math.sin(2 * math.pi * f * i / RATE)
            for i in range(int(RATE * 0.18))
            for f in (620,)
        ],
    )
    for file in sorted(out.glob("*.wav")):
        print(file.name, file.stat().st_size, "bytes")


if __name__ == "__main__":
    main()
