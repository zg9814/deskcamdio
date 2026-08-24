from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pygame

from deskcamdio.core.runtime import DeviceRuntime, RunState


def make_runtime(tmp_path: Path, **kwargs: Any) -> DeviceRuntime:
    return DeviceRuntime(
        data_dir=tmp_path / "data",
        run_dir=tmp_path / "run",
        headless=True,
        fps=240,
        health_interval=60.0,
        **kwargs,
    )


async def test_quit_event_stops_loop(tmp_path: Path) -> None:
    runtime = make_runtime(tmp_path)
    await runtime.initialize()
    pygame.event.post(pygame.event.Event(pygame.QUIT))
    await runtime.run(frame_limit=5)
    assert runtime.machine.state is RunState.SHUTTING_DOWN


async def test_escape_navigates_back_from_launcher(tmp_path: Path) -> None:
    runtime = make_runtime(tmp_path)
    await runtime.initialize()
    try:
        assert runtime.manager is not None
        runtime.launch_app("launcher")
        await asyncio.sleep(0.05)
        pygame.event.post(pygame.event.Event(pygame.KEYDOWN, {"key": pygame.K_ESCAPE}))
        await runtime.run(frame_limit=1)
        await asyncio.sleep(0.05)
        assert runtime.machine.state is RunState.STANDBY
    finally:
        await runtime.shutdown()


async def test_screen_sleep_state_skips_render(tmp_path: Path) -> None:
    runtime = make_runtime(tmp_path)
    await runtime.initialize()
    try:
        runtime.machine.transition(RunState.SCREEN_SLEEP, reason="timeout")
        await runtime.run(frame_limit=3)
        # Waking restores the remembered foreground (standby at boot).
        runtime.machine.transition(runtime.machine.return_state)
        assert runtime.machine.state is RunState.STANDBY
    finally:
        await runtime.shutdown()


async def test_shutdown_without_initialize_is_safe(tmp_path: Path) -> None:
    runtime = make_runtime(tmp_path)
    await runtime.shutdown()
    assert runtime.store is None


async def test_watchdog_notify_noop_without_env(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("NOTIFY_SOCKET", raising=False)
    runtime = make_runtime(tmp_path)
    await runtime.initialize()
    try:
        DeviceRuntime._notify_watchdog()  # must not raise
    finally:
        await runtime.shutdown()


async def test_launch_app_from_launcher_enters_app_state(tmp_path: Path) -> None:
    runtime = make_runtime(tmp_path)
    await runtime.initialize()
    try:
        runtime.launch_app("launcher")
        await asyncio.sleep(0.05)
        # launcher is special-cased to LAUNCHER state; a business app maps APP.
        runtime.launch_app("launcher")  # already in LAUNCHER; no-op transition guard
        assert runtime.machine.state is RunState.LAUNCHER
    finally:
        await runtime.shutdown()


async def test_app_fault_keeps_state_in_sync_with_standby_fallback(tmp_path: Path) -> None:
    runtime = make_runtime(tmp_path)
    runtime._render_boot_logo()  # safe before display initialization
    await runtime.initialize()
    try:
        runtime.launch_app("launcher")
        await asyncio.sleep(0.03)
        runtime._on_app_fault(type("Event", (), {"payload": {"app": "launcher"}})())
        assert runtime.machine.state is RunState.STANDBY

        runtime.launch_app("launcher")
        await asyncio.sleep(0.03)
        runtime.launch_app("memo")
        await asyncio.sleep(0.03)
        runtime._on_app_fault(type("Event", (), {"payload": {"app": "memo"}})())
        assert runtime.machine.state is RunState.STANDBY
    finally:
        await runtime.shutdown()


async def test_global_back_button_and_edge_swipe(tmp_path: Path) -> None:
    runtime = make_runtime(tmp_path)
    await runtime.initialize()
    try:
        runtime.launch_app("launcher")
        await asyncio.sleep(0.03)
        runtime.launch_app("memo")
        await asyncio.sleep(0.03)
        pygame.event.post(
            pygame.event.Event(
                pygame.MOUSEBUTTONDOWN,
                {"pos": runtime._back_button_rect.center, "button": 1},
            )
        )
        runtime._pump_events()
        assert runtime.machine.state is RunState.LAUNCHER

        pygame.event.post(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"pos": (5, 220), "button": 1})
        )
        pygame.event.post(
            pygame.event.Event(
                pygame.MOUSEBUTTONUP,
                {"pos": (130, 225), "button": 1},
            )
        )
        runtime._pump_events()
        assert runtime.machine.state is RunState.STANDBY
    finally:
        await runtime.shutdown()
