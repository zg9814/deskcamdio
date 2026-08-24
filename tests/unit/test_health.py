from __future__ import annotations

import json
from pathlib import Path

from deskcamdio.core.health import _read_status_field, build_snapshot, sample_process, write_health

SAMPLE = """VmRSS:\t 99000 kB\nVmSwap:\t 100 kB\nOther: x\nPss:\t 50000 kB\n"""


def test_read_status_field_parses_kb_values() -> None:
    assert _read_status_field(SAMPLE, "VmRSS") == 99000
    assert _read_status_field(SAMPLE, "Pss") == 50000
    assert _read_status_field(SAMPLE, "Missing") == 0


def test_sample_process_degrades_on_windows(monkeypatch) -> None:
    monkeypatch.setattr(Path, "read_text", lambda *a, **k: (_ for _ in ()).throw(OSError()))
    values = sample_process()
    assert set(values) == {"rss_kb", "pss_kb", "fd_count"}


def test_build_snapshot_shape() -> None:
    snapshot = build_snapshot(
        version="1.0.0",
        active_app="standby",
        mode="STANDBY",
        workers={"camera": "down"},
        last_frame_ms=12.3456,
        last_error="",
    )
    assert snapshot["version"] == "1.0.0"
    assert snapshot["mode"] == "STANDBY"
    assert snapshot["last_frame_ms"] == 12.35
    assert snapshot["workers"] == {"camera": "down"}


def test_write_health_atomic(tmp_path: Path) -> None:
    target = tmp_path / "run" / "health.json"
    write_health(target, {"rss_kb": 1})
    assert json.loads(target.read_text(encoding="utf-8")) == {"rss_kb": 1}
    leftovers = list(target.parent.glob("*.tmp"))
    assert leftovers == []
