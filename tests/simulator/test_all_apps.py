"""Simulator smoke: every app mounts, enters, renders headlessly."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pygame
import pytest

from deskcamdio.core.app_manager import AppManager
from deskcamdio.core.events import EventBus
from deskcamdio.core.lifecycle import RouteState

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

APP_IDS = [
    "standby",
    "launcher",
    "camera",
    "gallery",
    "music",
    "gba",
    "ps1",
    "fishing",
    "memo",
    "pomodoro",
    "settings",
]


@pytest.fixture(scope="module", autouse=True)
def _pygame_init():
    pygame.display.init()
    pygame.font.init()
    yield
    pygame.quit()


def surface() -> pygame.Surface:
    return pygame.Surface((480, 480))


async def make_manager(tmp_path: Path) -> AppManager:
    from deskcamdio.core.runtime import RunState, RuntimeContext, RuntimeStateMachine
    from deskcamdio.services.audio import AudioService
    from deskcamdio.services.state_store import StateStore

    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    machine = RuntimeStateMachine(initial=RunState.STANDBY)
    audio = AudioService()
    bus = EventBus()
    store = StateStore(tmp_path / "data" / "state.db", bus)
    await store.start()

    def factory(_app_id: str, scope: Any = None) -> RuntimeContext:
        return RuntimeContext(
            store=store,
            bus=bus,
            machine=machine,
            audio=audio,
            data_dir=tmp_path / "data",
            launch=lambda _target: None,
            scope=scope,
        )

    manager = AppManager(
        bus=bus,
        context_factory=factory,
        apps_root=Path(__import__("deskcamdio.apps", fromlist=["apps"]).__file__).parent,
    )
    manager._test_store = store  # type: ignore[attr-defined]
    return manager


@pytest.mark.parametrize("app_id", APP_IDS)
async def test_app_mount_enter_update_render(tmp_path: Path, app_id: str) -> None:
    manager = await make_manager(tmp_path)
    assert set(manager.descriptor_ids()) == set(APP_IDS)
    await manager.enter(RouteState(app_id=app_id))
    assert manager.active_id == app_id
    manager.handle_input(pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"pos": (240, 240)}))
    for _ in range(3):
        manager.update(1 / 30)
    manager.render(surface())
    await manager.leave_current()
    if app_id != "standby":
        assert not manager.is_mounted(app_id)


async def test_fishing_full_round(tmp_path: Path) -> None:
    manager = await make_manager(tmp_path)
    await manager.enter(RouteState(app_id="fishing"))
    mounted = manager._mounted["fishing"]
    app = mounted.app
    app.player.energy = 100
    app.bait_left = 5
    app._start_trip()
    fish = next(item for item in app.world.fish if item.size == "small")
    fish.state = "bite"
    fish.bite_deadline = app.world.time + 10
    cargo_before = len(app.cargo)
    app._reel()
    for _ in range(120):
        app.update(1 / 30)
        if len(app.cargo) > cargo_before:
            break
    assert len(app.cargo) == cargo_before + 1
    await manager.leave_current()
