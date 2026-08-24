"""Runtime wiring of TouchRelay (integration: real DeviceRuntime)."""

from __future__ import annotations

import os
from pathlib import Path

from deskcamdio.core.runtime import DeviceRuntime


def _dummy_sdl() -> None:
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")


async def _make_visible_runtime(tmp_path: Path) -> DeviceRuntime:
    _dummy_sdl()
    runtime = DeviceRuntime(
        data_dir=tmp_path / "data",
        run_dir=tmp_path / "run",
        headless=False,  # relay only arms outside headless mode
        fps=240,
        health_interval=3600,
    )
    await runtime.initialize()
    return runtime


async def test_runtime_wires_touch_relay_on_raspi(tmp_path: Path, monkeypatch) -> None:
    import deskcamdio.services.touch_relay as tr

    monkeypatch.setenv("DESKCAMDIO_PLATFORM", "raspberry_pi")
    monkeypatch.setattr(tr, "discover_touch_device", lambda: "/dev/input/eventX")
    monkeypatch.setattr(tr.TouchRelay, "start", lambda self: None)
    rt = await _make_visible_runtime(tmp_path / "wired")
    try:
        assert rt._touch_relay is not None
        assert rt._touch_relay.path == "/dev/input/eventX"
    finally:
        await rt.shutdown()
    assert rt._touch_relay is None


async def test_runtime_warns_without_touch_device(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DESKCAMDIO_PLATFORM", "raspberry_pi")
    rt = await _make_visible_runtime(tmp_path / "unwired")
    try:
        assert rt._touch_relay is None
    finally:
        await rt.shutdown()


async def test_runtime_skips_relay_when_headless(tmp_path: Path, monkeypatch) -> None:
    from test_input_flow import make_runtime  # type: ignore[import-not-found]

    monkeypatch.setenv("DESKCAMDIO_PLATFORM", "raspberry_pi")
    rt = await make_runtime(tmp_path / "headless")
    try:
        assert rt._touch_relay is None
    finally:
        await rt.shutdown()
