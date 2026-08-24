"""Process health sampling.

Reads /proc on Linux (Pi). On Windows the numbers degrade gracefully to 0 so
the simulator can still produce a health.json.
"""

from __future__ import annotations

import contextlib
import logging
import os
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)


def _read_status_field(status_text: str, field_name: str) -> int:
    for line in status_text.splitlines():
        if line.startswith(field_name + ":"):
            value = line.split(":", 1)[1].strip().split()[0]
            return int(value)
    return 0


def sample_process() -> dict[str, int]:
    rss_kb = pss_kb = fd_count = 0
    try:
        status = Path("/proc/self/status").read_text(encoding="ascii", errors="ignore")
        rss_kb = _read_status_field(status, "VmRSS")
    except OSError:
        pass
    try:
        rollup = Path("/proc/self/smaps_rollup").read_text(encoding="ascii", errors="ignore")
        pss_kb = _read_status_field(rollup, "Pss")
    except OSError:
        pass
    with contextlib.suppress(OSError):
        fd_count = len(os.listdir("/proc/self/fd"))
    return {"rss_kb": rss_kb, "pss_kb": pss_kb, "fd_count": fd_count}


def sample_system() -> dict[str, int]:
    available_kb = swap_used_kb = 0
    try:
        meminfo = Path("/proc/meminfo").read_text(encoding="ascii", errors="ignore")
        available_kb = _read_status_field(meminfo, "MemAvailable")
        swap_used_kb = _read_status_field(meminfo, "SwapTotal") - _read_status_field(
            meminfo, "SwapFree"
        )
    except OSError:
        pass
    return {"available_memory_kb": available_kb, "swap_used_kb": max(0, swap_used_kb)}


class HealthSnapshot(dict[str, Any]):
    pass


def build_snapshot(
    version: str,
    active_app: str,
    mode: str,
    workers: dict[str, Any],
    last_frame_ms: float,
    last_error: str,
) -> dict[str, Any]:
    snapshot: dict[str, Any] = {
        "version": version,
        "active_app": active_app,
        "mode": mode,
        **sample_process(),
        **sample_system(),
        "workers": workers,
        "last_frame_ms": round(last_frame_ms, 2),
        "last_error": last_error,
    }
    return snapshot


def write_health(path: Path, snapshot: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    import json

    tmp.write_text(json.dumps(snapshot), encoding="utf-8")
    os.replace(tmp, path)
