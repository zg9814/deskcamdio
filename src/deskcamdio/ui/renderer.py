"""Frame chrome: background wash and the status bar (guide §9)."""

from __future__ import annotations

import time

import pygame

from deskcamdio.ui.themes import ThemeTokens
from deskcamdio.ui.typography import render_text


def background(surface: pygame.Surface, theme: ThemeTokens) -> None:
    from deskcamdio.ui.aquarium import gradient

    gradient(surface, theme)


def status_bar(
    surface: pygame.Surface,
    theme: ThemeTokens,
    *,
    hostname: str = "fishpi",
    online: bool = True,
    bluetooth: bool = False,
    battery: str = "",
) -> None:
    stamp = time.strftime("%H:%M")
    clock_surface = render_text(stamp, 15, theme.text_primary, bold=True)
    surface.blit(clock_surface, (12, 4))

    right_x = surface.get_width() - 12
    if battery:
        battery_text = render_text(battery, 13, theme.text_secondary)
        right_x -= battery_text.get_width()
        surface.blit(battery_text, (right_x, 6))
        right_x -= 8

    dot_color = theme.accent if bluetooth else theme.stroke
    pygame.draw.circle(surface, dot_color, (right_x - 5, 11), 4)
    right_x -= 16

    net_color = theme.text_secondary if online else theme.danger
    pygame.draw.circle(surface, net_color, (right_x - 5, 11), 4)

    name = render_text(hostname[:7], 13, theme.text_secondary)
    right_x -= name.get_width() + 10
    surface.blit(name, (right_x, 6))
