from __future__ import annotations

import os

import pygame
import pytest

from deskcamdio.core.lifecycle import LeaveReason, RouteState


@pytest.fixture(scope="module", autouse=True)
def _display():
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    pygame.display.init()
    pygame.font.init()
    yield


def make_surface() -> pygame.Surface:
    return pygame.Surface((480, 480))


async def test_standby_full_cycle() -> None:
    from deskcamdio.apps.standby.app import StandbyApp

    app = StandbyApp()
    await app.mount(context=None)
    await app.enter(RouteState(app_id="standby"))
    app.update(0.5)
    surface = make_surface()
    app.render(surface)
    await app.leave(LeaveReason.SUPERSEDED)
    await app.dispose()
    assert app._fish == []


async def test_launcher_page_from_route_args() -> None:
    from deskcamdio.apps.launcher.app import LauncherApp

    app = LauncherApp()
    await app.mount(context=None)
    await app.enter(RouteState(app_id="launcher", args={"page": "1"}))
    surface = make_surface()
    app.render(surface)
    assert surface.get_at((16, 12)) is not None
    app.handle_input(pygame.event.Event(pygame.NOEVENT))
    await app.leave(LeaveReason.NAVIGATED_BACK)
    await app.dispose()


async def test_launcher_default_page_zero() -> None:
    from deskcamdio.apps.launcher.app import LauncherApp

    app = LauncherApp()
    await app.mount(context=None)
    await app.enter(RouteState(app_id="launcher"))
    assert app.page == 0
