from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from deskcamdio.core.lifecycle import RouteState
from deskcamdio.core.runtime import DeviceRuntime, RunState


class ManagerStub:
    def __init__(self, ids: list[str]) -> None:
        self.active_id = ""
        self._ids = ids
        self.entered: list[str] = []

    def descriptor_ids(self) -> list[str]:
        return self._ids

    async def enter(self, route: RouteState) -> None:
        self.active_id = route.app_id
        self.entered.append(route.app_id)

    async def leave_current(self, reason: Any = None) -> None:
        self.active_id = ""

    async def dispose_all(self) -> None:
        return


@pytest.fixture()
def runtime(tmp_path: Path) -> DeviceRuntime:
    rt = DeviceRuntime(
        data_dir=tmp_path / "data",
        run_dir=tmp_path / "run",
        headless=True,
        fps=240,
        health_interval=0.02,
    )
    return rt


async def test_launch_from_standby_opens_launcher(runtime: DeviceRuntime) -> None:
    await runtime.initialize()
    try:
        assert runtime.manager is not None
        runtime.manager = ManagerStub(["standby", "launcher", "memo"])  # type: ignore[assignment]
        runtime.launch_app("launcher")
        await asyncio.sleep(0)
        assert runtime.machine.state is RunState.LAUNCHER

        runtime.launch_app("memo")
        await asyncio.sleep(0)
        assert runtime.machine.state is RunState.APP
        assert runtime.manager.entered[-1] == "memo"
    finally:
        await runtime.shutdown()


async def test_back_from_app_returns_to_launcher_then_standby(
    runtime: DeviceRuntime, tmp_path: Path
) -> None:
    await runtime.initialize()
    try:
        runtime.manager = ManagerStub(["standby", "launcher", "memo"])  # type: ignore[assignment]
        runtime.manager.entered.append("launcher")
        runtime.machine.transition(RunState.LAUNCHER)
        runtime.machine.transition(RunState.APP)
        runtime.manager.active_id = "memo"

        runtime.navigate_back()
        await asyncio.sleep(0)
        assert runtime.machine.state is RunState.LAUNCHER

        runtime.navigate_back()
        await asyncio.sleep(0)
        assert runtime.machine.state is RunState.STANDBY
    finally:
        await runtime.shutdown()


async def test_request_shutdown_is_terminal_and_stops_loop(
    runtime: DeviceRuntime,
) -> None:
    await runtime.initialize()
    runtime.request_shutdown("test")
    runtime.request_shutdown("again")  # swallowed; state already terminal
    assert runtime.machine.state is RunState.SHUTTING_DOWN
    await runtime.run(frame_limit=1)
    assert runtime.running is False


async def test_health_file_written(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    runtime = DeviceRuntime(
        data_dir=tmp_path / "data",
        run_dir=run_dir,
        headless=True,
        fps=240,
        health_interval=0.01,
    )
    await runtime.initialize()
    await asyncio.sleep(0.05)
    await runtime.shutdown()
    health = run_dir / "health.json"
    assert health.exists()
