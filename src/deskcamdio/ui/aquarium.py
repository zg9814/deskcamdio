"""Low-allocation aquarium scene shared by standby and themed empty states."""

from __future__ import annotations

import math
from importlib.resources import files

import pygame

from deskcamdio.ui.themes import ThemeTokens

_props: dict[str, pygame.Surface] = {}
_scaled: dict[tuple[str, int], pygame.Surface] = {}


def gradient(surface: pygame.Surface, theme: ThemeTokens) -> None:
    height = surface.get_height()
    for y in range(height):
        ratio = y / max(1, height - 1)
        color = tuple(
            round(theme.background_top[i] * (1 - ratio) + theme.background_bottom[i] * ratio)
            for i in range(3)
        )
        pygame.draw.line(surface, color, (0, y), (surface.get_width(), y))


def ambient(surface: pygame.Surface, theme: ThemeTokens, elapsed: float) -> None:
    gradient(surface, theme)
    wash = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
    pygame.draw.rect(wash, (*theme.water, 92), (0, 74, 480, 330))
    for band in range(4):
        y = 88 + band * 86
        phase = elapsed * (0.30 + band * 0.04) + band * 1.5
        points = [
            (x, round(y + math.sin(x * 0.024 + phase) * (4 + band))) for x in range(0, 481, 16)
        ]
        pygame.draw.aalines(wash, (*theme.accent, 76), False, points)
    for index in range(8):
        by = 398 - ((elapsed * (10 + index * 1.7) + index * 57) % 370)
        bx = 34 + (index * 71 + math.sin(elapsed * 0.8 + index) * 15) % 410
        pygame.draw.circle(wash, (*theme.accent, 108), (round(bx), round(by)), 2 + index % 4, 1)
    surface.blit(wash, (0, 0))


def seabed(surface: pygame.Surface, theme: ThemeTokens, elapsed: float) -> None:
    points = [(0, 396)]
    points += [
        (x, round(394 + math.sin(x * 0.032 + elapsed * 0.45) * 5)) for x in range(0, 481, 16)
    ]
    points += [(480, 480), (0, 480)]
    pygame.draw.polygon(surface, theme.sand, points)
    placements = (
        ("seaweed_3", 48, 428, 3.3, 0.0),
        ("flora_1", 112, 432, 2.9, 0.8),
        ("bush_1", 358, 434, 3.0, 1.7),
        ("flora_4", 421, 428, 3.0, 2.4),
    )
    for name, x, bottom, scale, phase in placements:
        image = prop(name, scale)
        if image is None:
            continue
        sway = round(math.sin(elapsed * 1.25 + phase) * 4)
        surface.blit(image, image.get_rect(midbottom=(x + sway, bottom)))


def prop(name: str, scale: float) -> pygame.Surface | None:
    if name not in _props:
        try:
            path = files("deskcamdio.assets.aquatic").joinpath(f"{name}.png")
            with path.open("rb") as stream:
                _props[name] = pygame.image.load(stream, f"{name}.png").convert_alpha()
        except (FileNotFoundError, ModuleNotFoundError, pygame.error):
            return None
    key = (name, round(scale * 10))
    if key not in _scaled:
        source = _props[name]
        _scaled[key] = pygame.transform.scale(
            source, (round(source.get_width() * scale), round(source.get_height() * scale))
        )
    return _scaled[key]


def clear_caches() -> None:
    _props.clear()
    _scaled.clear()
