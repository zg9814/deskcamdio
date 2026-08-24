"""Shared fixtures: headless pygame + real AppManager/StateStore harness."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import pygame
import pytest

from deskcamdio.apps import apps_root_path
from deskcamdio.core.app_manager import AppManager
from deskcamdio.core.events import EventBus
from deskcamdio.core.lifecycle import LeaveReason, RouteState
from deskcamdio.core.runtime import RunState, RuntimeContext, RuntimeStateMachine
from deskcamdio.services.audio import AudioService
from deskcamdio.services.state_store import StateStore

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")


class Harness:
    """Boots a real AppManager + StateStore against the packaged applications."""

    def __init__(self, tmp_path: Path, launch: Callable[[str], None] | None = None) -> None:
        self.data_dir = tmp_path / "data"
        self.run_dir = tmp_path / "run"
        self.bus = EventBus()
        self.machine = RuntimeStateMachine(initial=RunState.STANDBY)
        self.audio = AudioService()
        self.system: Any = None
        self.store = StateStore(self.data_dir / "state.db", self.bus)
        self._launch = launch
        self.manager = AppManager(
            bus=self.bus,
            context_factory=self._context,
            apps_root=apps_root_path(),
        )

    def _context(self, _app_id: str, scope: Any = None) -> RuntimeContext:
        from deskcamdio.platform.system import SimulatedSystem

        if self.system is None:
            self.system = SimulatedSystem()
        return RuntimeContext(
            store=self.store,
            bus=self.bus,
            machine=self.machine,
            audio=self.audio,
            data_dir=self.data_dir,
            launch=self._launch,
            scope=scope,
            system=self.system,
        )

    async def start(self) -> Harness:
        await self.store.start()
        import contextlib

        with contextlib.suppress(Exception):
            self.audio.open_mixer()
        return self

    async def open(self, app_id: str) -> Any:
        await self.manager.enter(RouteState(app_id=app_id))
        return self.manager._mounted[app_id].app


@pytest.fixture(scope="session", autouse=True)
def _pygame_headless() -> AsyncIterator[None]:
    if not pygame.display.get_init():
        pygame.display.init()
    if not pygame.font.get_init():
        pygame.font.init()
    yield


@pytest.fixture()
async def harness(tmp_path: Path) -> AsyncIterator[Harness]:
    instance = await Harness(tmp_path).start()
    yield instance
    await instance.manager.leave_current(LeaveReason.SHUTDOWN)
    await instance.manager.dispose_all()
    await instance.store.close()


@pytest.fixture()
async def harness_maker(tmp_path: Path) -> AsyncIterator[Callable[..., Any]]:
    instances: list[Harness] = []

    async def make(**kwargs: Any) -> Harness:
        instance = await Harness(tmp_path / f"case{len(instances)}", **kwargs).start()
        instances.append(instance)
        return instance

    yield make

    for instance in instances:
        await instance.manager.leave_current(LeaveReason.SHUTDOWN)
        await instance.manager.dispose_all()
        await instance.store.close()
