from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

import pygame
import pytest

from deskcamdio.core.app_manager import AppManager, load_descriptors
from deskcamdio.core.events import EventBus
from deskcamdio.core.lifecycle import LeaveReason, RouteState


class Recorder:
    def __init__(self, name: str, fail_on: str = "", leave_delay: float = 0.0) -> None:
        self.name = name
        self.fail_on = fail_on
        self.leave_delay = leave_delay
        self.calls: list[str] = []
        self.entered = False

    async def mount(self, context: Any) -> None:
        self.calls.append("mount")
        if self.fail_on == "mount":
            raise RuntimeError("mount boom")

    async def enter(self, route: RouteState) -> None:
        self.calls.append(f"enter:{route.app_id}")
        self.entered = True
        if self.fail_on == "enter":
            raise RuntimeError("enter boom")

    def handle_input(self, event: Any) -> None:
        self.calls.append("input")

    def update(self, delta_seconds: float) -> None:
        self.calls.append("update")

    def render(self, surface: Any) -> None:
        self.calls.append("render")

    async def leave(self, reason: LeaveReason) -> None:
        self.calls.append(f"leave:{reason.name}")
        self.entered = False
        if self.leave_delay:
            await asyncio.sleep(self.leave_delay)

    async def dispose(self) -> None:
        self.calls.append("dispose")


def build_manager(tmp_path: Path, apps: dict[str, Recorder]) -> AppManager:
    (tmp_path / "apps" / "standby").mkdir(parents=True)
    manager = AppManager(
        bus=EventBus(), context_factory=lambda _id, _s: object(), apps_root=tmp_path / "apps"
    )
    return manager


async def test_descriptors_require_api_version_2(tmp_path: Path) -> None:
    good = tmp_path / "good"
    bad = tmp_path / "bad"
    good.mkdir()
    bad.mkdir()
    (good / "app.toml").write_text(
        'id="good"\nname="g"\napi_version=2\nentrypoint="x:y"\norder=1\n', encoding="utf-8"
    )
    (bad / "app.toml").write_text(
        'id="bad"\nname="b"\napi_version=1\nentrypoint="x:y"\norder=2\n', encoding="utf-8"
    )
    descriptors = load_descriptors(tmp_path)
    assert [d.app_id for d in descriptors] == ["good"]


async def test_enter_leave_dispose_sequence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = build_manager(tmp_path, {})
    recorder = Recorder("memo")
    _install(manager, "memo", recorder)
    standby = Recorder("standby")
    _install(manager, "standby", standby)

    await manager.enter(RouteState(app_id="standby"))
    assert standby.calls == ["enter:standby"]  # pre-mounted via _install
    assert manager.active_id == "standby"

    await manager.enter(RouteState(app_id="memo"))
    assert recorder.calls == ["enter:memo"]
    assert standby.entered is False and manager.is_mounted("standby")

    await manager.enter(RouteState(app_id="standby"), LeaveReason.NAVIGATED_BACK)
    assert recorder.calls[-2:] == ["leave:NAVIGATED_BACK", "dispose"]
    assert not manager.is_mounted("memo")


def _install(manager: AppManager, app_id: str, app: Any) -> None:
    from deskcamdio.core.app_manager import _Mounted
    from deskcamdio.core.task_scope import TaskScope

    mounted = _Mounted(app_id=app_id, app=app, scope=TaskScope(f"app:{app_id}"))
    manager._mounted[app_id] = mounted
    manager.descriptors[app_id] = manager.descriptors.get(app_id) or _descriptor(app_id)


def _descriptor(app_id: str) -> Any:
    from deskcamdio.core.app_manager import AppDescriptor

    return AppDescriptor(
        app_id=app_id,
        name=app_id,
        icon="",
        order=10,
        api_version=2,
        entrypoint=f"fixture_apps.{app_id}:APP",
    )


async def test_standby_stays_resident(tmp_path: Path) -> None:
    manager = build_manager(tmp_path, {})
    standby = Recorder("standby")
    memo = Recorder("memo")
    _install(manager, "standby", standby)
    _install(manager, "memo", memo)

    await manager.enter(RouteState(app_id="standby"))
    await manager.enter(RouteState(app_id="memo"))
    await manager.leave_current(LeaveReason.NAVIGATED_BACK)

    assert manager.is_mounted("standby")
    assert not manager.is_mounted("memo")
    assert "dispose" not in standby.calls


async def test_fault_in_enter_falls_back_to_standby(tmp_path: Path) -> None:
    manager = build_manager(tmp_path, {})
    broken = Recorder("broken", fail_on="enter")
    standby = Recorder("standby")
    _install(manager, "standby", standby)
    _install(manager, "broken", broken)

    await manager.enter(RouteState(app_id="broken"))
    assert manager.active_id == "standby"
    assert "dispose" in broken.calls
    assert "enter:standby" in standby.calls


async def test_leave_timeout_forced_but_scope_closed(tmp_path: Path) -> None:
    manager = build_manager(tmp_path, {})
    slow = Recorder("slow", leave_delay=2.0)
    standby = Recorder("standby")
    _install(manager, "standby", standby)
    _install(manager, "slow", slow)

    started = asyncio.get_running_loop().time()
    await manager.enter(RouteState(app_id="slow"))
    await manager.leave_current(LeaveReason.SUPERSEDED)
    elapsed = asyncio.get_running_loop().time() - started
    assert elapsed < 1.5  # bounded by LEAVE_TIMEOUT + dispose overhead
    assert "dispose" in slow.calls


async def test_input_update_render_faults_schedule_fallback(tmp_path: Path) -> None:
    class Exploder(Recorder):
        def handle_input(self, event: Any) -> None:
            raise RuntimeError("input boom")

    manager = build_manager(tmp_path, {})
    exploding = Exploder("exploding")
    standby = Recorder("standby")
    _install(manager, "standby", standby)
    _install(manager, "exploding", exploding)

    event = pygame.event.Event(pygame.NOEVENT)
    await manager.enter(RouteState(app_id="exploding"))
    assert manager.handle_input(event) is False
    await asyncio.sleep(0.05)  # allow fallback task to run
    assert manager.active_id == "standby"


async def test_unknown_app_raises(tmp_path: Path) -> None:
    manager = build_manager(tmp_path, {})
    with pytest.raises(KeyError):
        await manager.enter(RouteState(app_id="ghost"))


def test_pygame_import_guard_for_worker_rule() -> None:
    assert "picamera2" not in sys.modules
    assert "numpy" not in sys.modules
