"""Global status and pull-down control behavior."""

import pygame

from deskcamdio.ui.system_overlay import SystemOverlay
from deskcamdio.ui.themes import ThemeService


def _mouse(kind: int, pos: tuple[int, int]) -> pygame.event.Event:
    return pygame.event.Event(kind, {"button": 1, "pos": pos})


def test_pull_down_opens_and_volume_commits() -> None:
    overlay = SystemOverlay()
    assert overlay.handle_input(_mouse(pygame.MOUSEBUTTONDOWN, (200, 10)))
    assert overlay.handle_input(_mouse(pygame.MOUSEMOTION, (200, 180)))
    assert overlay.handle_input(_mouse(pygame.MOUSEBUTTONUP, (200, 180)))
    overlay.update(0.4)
    assert overlay.open

    overlay.handle_input(_mouse(pygame.MOUSEBUTTONDOWN, (240, 180)))
    action = overlay.handle_input(_mouse(pygame.MOUSEBUTTONUP, (240, 180)))
    assert action is not None and action[0] == "volume_commit"
    assert 45 <= action[1] <= 55


def test_status_and_panel_render() -> None:
    overlay = SystemOverlay(openness=1.0, _target=1.0)
    overlay.status.update({"wifi": True, "bluetooth": True, "controller": True})
    surface = pygame.Surface((480, 480))
    overlay.render(surface, ThemeService().tokens)
    assert surface.get_bounding_rect().width == 480
