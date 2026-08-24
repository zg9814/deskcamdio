"""End-to-end input routing: real pygame events through the runtime pump."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pygame

from deskcamdio.core.runtime import DeviceRuntime, RunState


async def make_runtime(tmp_path: Path) -> DeviceRuntime:
    os_environ_guard()
    runtime = DeviceRuntime(
        data_dir=tmp_path / "data",
        run_dir=tmp_path / "run",
        headless=True,
        fps=240,
        health_interval=3600,
    )
    await runtime.initialize()
    return runtime


def os_environ_guard() -> None:
    import os

    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")


def click(pos: tuple[int, int]) -> None:
    pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1, "pos": pos}))
    pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONUP, {"button": 1, "pos": pos}))


def key(keycode: int) -> None:
    pygame.event.post(pygame.event.Event(pygame.KEYDOWN, {"key": keycode}))


async def settle(runtime: DeviceRuntime, seconds: float = 0.08) -> None:
    """Pump queued events, let scheduled tasks run, drain follow-up events."""
    deadline = asyncio.get_running_loop().time() + seconds
    while asyncio.get_running_loop().time() < deadline:
        runtime._pump_events()
        await asyncio.sleep(0.01)


async def test_tap_on_standby_opens_launcher(tmp_path: Path) -> None:
    runtime = await make_runtime(tmp_path)
    try:
        assert runtime.machine.state is RunState.STANDBY
        click((450, 250))
        await settle(runtime)
        assert runtime.machine.state is RunState.LAUNCHER
        assert runtime.manager is not None and runtime.manager.active_id == "launcher"
    finally:
        await runtime.shutdown()


async def test_launcher_tile_click_launches_app(tmp_path: Path) -> None:
    runtime = await make_runtime(tmp_path)
    try:
        click((450, 250))
        await settle(runtime)
        assert runtime.manager is not None
        launcher_host = runtime.manager._mounted["launcher"]
        surface = pygame.Surface((480, 480))
        launcher_host.app.render(surface)  # build tile hitboxes

        camera_tile = launcher_host.app._tiles["camera"]
        click(camera_tile.center)
        await settle(runtime)

        assert runtime.machine.state is RunState.APP
        assert runtime.manager.active_id == "camera"
    finally:
        await runtime.shutdown()


async def test_escape_walks_back_to_standby(tmp_path: Path) -> None:
    runtime = await make_runtime(tmp_path)
    try:
        click((450, 250))
        await settle(runtime)
        key(pygame.K_ESCAPE)
        await settle(runtime)
        assert runtime.machine.state is RunState.STANDBY

        # Forward again to APP, then two escapes walk APP→LAUNCHER→STANDBY.
        click((450, 250))
        await settle(runtime)
        runtime.launch_app("memo")
        await settle(runtime)
        assert runtime.machine.state is RunState.APP

        key(pygame.K_ESCAPE)
        await settle(runtime)
        assert runtime.machine.state is RunState.LAUNCHER
        key(pygame.K_ESCAPE)
        await settle(runtime)
        assert runtime.machine.state is RunState.STANDBY
    finally:
        await runtime.shutdown()


async def test_events_reach_active_app_update_loop(tmp_path: Path) -> None:
    """Standby fish move only when update runs — proves frame loop wiring."""
    runtime = await make_runtime(tmp_path)
    try:
        assert runtime.manager is not None
        host = runtime.manager._mounted["standby"]
        before = [f.x for f in host.app._fish]
        runtime.manager.update(1 / 30)
        after = [f.x for f in host.app._fish]
        assert before != after
    finally:
        await runtime.shutdown()
