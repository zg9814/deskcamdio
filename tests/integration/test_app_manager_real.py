from __future__ import annotations

from pathlib import Path

import pygame

import deskcamdio.apps
from deskcamdio.core.app_manager import AppManager, instantiate, load_descriptors
from deskcamdio.core.events import EventBus
from deskcamdio.core.lifecycle import RouteState


def test_packaged_descriptors_load() -> None:
    root = Path(desktop_apps_root())
    descriptors = load_descriptors(root)
    ids = {d.app_id for d in descriptors}
    assert {"standby", "launcher"} <= ids


def desktop_apps_root() -> str:
    from pathlib import Path as _P

    return str(_P(deskcamdio.apps.__file__).parent)


async def test_real_app_full_frame_flow(tmp_path: Path) -> None:
    os_env_dummy()
    pygame.display.init()
    pygame.font.init()
    try:
        surface = pygame.Surface((480, 480))
        manager = AppManager(
            bus=EventBus(),
            context_factory=lambda _app_id, _s: None,
            apps_root=Path(desktop_apps_root()),
        )
        await manager.enter(RouteState(app_id="launcher"))
        assert manager.active_id == "launcher"

        consumed = manager.handle_input(pygame.event.Event(pygame.NOEVENT))
        assert consumed is True
        manager.update(1 / 60)
        manager.render(surface)

        await manager.leave_current()
        assert not manager.is_mounted("launcher")
    finally:
        pygame.font.quit()
        pygame.display.quit()


async def test_instantiate_loads_entrypoint_class() -> None:
    app = instantiate("deskcamdio.apps.launcher.app:LauncherApp")
    assert type(app).__name__ == "LauncherApp"


def os_env_dummy() -> None:
    import os

    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")


async def test_fallback_without_standby_no_crash(tmp_path: Path, monkeypatch) -> None:
    manager = AppManager(
        bus=EventBus(), context_factory=lambda _i, _s: None, apps_root=tmp_path / "empty"
    )
    monkeypatch.delitem(manager.descriptors, "standby", raising=False)
    manager.descriptors["solo"] = manager.descriptors.get("solo") or _make_descriptor("solo")
    from deskcamdio.core.app_manager import _Mounted
    from deskcamdio.core.task_scope import TaskScope

    class Boom:
        async def enter(self, route):  # noqa: ANN001
            raise RuntimeError("boom")

        async def dispose(self):  # noqa: ANN001
            return

    mounted = _Mounted(app_id="solo", app=Boom(), scope=TaskScope("solo"))
    manager._mounted["solo"] = mounted
    manager.active_id = ""
    await manager._fallback("solo")
    assert "solo" not in manager._mounted


def _make_descriptor(app_id: str):
    from deskcamdio.core.app_manager import AppDescriptor

    return AppDescriptor(
        app_id=app_id,
        name=app_id,
        icon="",
        order=10,
        api_version=2,
        entrypoint="deskcamdio.apps.launcher.app:LauncherApp",
    )
