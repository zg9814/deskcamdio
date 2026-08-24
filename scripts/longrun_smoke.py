"""10,000-frame headless soak with P50/P95 frame timing (guide §15)."""

from __future__ import annotations

import argparse
import asyncio
import statistics
import tempfile
import time
from pathlib import Path


class _NoDelayClock:
    def tick(self, _fps: int) -> int:
        return 0


async def soak(frames: int, fps: int) -> dict[str, float]:
    from deskcamdio.core.runtime import DeviceRuntime

    with tempfile.TemporaryDirectory() as tmp:
        runtime = DeviceRuntime(
            data_dir=Path(tmp) / "data",
            run_dir=Path(tmp) / "run",
            headless=True,
            fps=fps,
            health_interval=3600,
        )
        await runtime.initialize()
        runtime.clock = _NoDelayClock()  # type: ignore[assignment]
        history = runtime.frame_ms_history
        started = time.monotonic()
        await runtime.run(frame_limit=frames)
        wall = time.monotonic() - started

    samples = sorted(history)
    return {
        "frames": len(samples),
        "wall_s": round(wall, 2),
        "p50_ms": round(statistics.median(samples), 3),
        "p95_ms": round(samples[int(len(samples) * 0.95)], 3),
        "max_ms": round(samples[-1], 3),
        "fps_effective": round(len(samples) / wall, 1),
    }


def main() -> None:
    parser = argparse.ArgumentParser(prog="longrun_smoke")
    parser.add_argument("--frames", type=int, default=10_000)
    parser.add_argument("--fps", type=int, default=1000)
    args = parser.parse_args()

    result = asyncio.run(soak(args.frames, args.fps))
    print("=== LONGRUN RESULT ===")
    for key, value in result.items():
        print(f"{key}={value}")


if __name__ == "__main__":
    main()
