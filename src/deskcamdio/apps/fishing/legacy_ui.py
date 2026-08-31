"""Compatibility drawing helpers for the richer pre-v1 fishing game."""

from __future__ import annotations

from dataclasses import dataclass

import pygame

from deskcamdio.ui import components
from deskcamdio.ui.themes import ThemeTokens
from deskcamdio.ui.typography import render_text, wrap_text


@dataclass(frozen=True, slots=True)
class Palette:
    text: tuple[int, int, int]
    muted: tuple[int, int, int]
    accent: tuple[int, int, int]
    accent_soft: tuple[int, int, int]
    surface: tuple[int, int, int]
    surface_alt: tuple[int, int, int]
    warning: tuple[int, int, int]
    danger: tuple[int, int, int]
    success: tuple[int, int, int]
    stroke: tuple[int, int, int]
    shadow: tuple[int, int, int]


_tokens: ThemeTokens | None = None


def use_theme(tokens: ThemeTokens) -> None:
    global _tokens
    _tokens = tokens


def palette() -> Palette:
    assert _tokens is not None
    return Palette(
        text=_tokens.text_primary,
        muted=_tokens.text_secondary,
        accent=_tokens.accent,
        accent_soft=_tokens.water,
        surface=_tokens.surface,
        surface_alt=_tokens.surface_elevated,
        warning=_tokens.warning,
        danger=_tokens.danger,
        success=(43, 166, 112),
        stroke=_tokens.stroke,
        shadow=(0, 0, 0),
    )


def __getattr__(name: str) -> tuple[int, int, int]:
    aliases = {
        "MUTED": "muted",
        "AMBER": "warning",
        "RED": "danger",
        "GREEN": "success",
    }
    if name in aliases:
        return getattr(palette(), aliases[name])
    raise AttributeError(name)


def text(
    surface: pygame.Surface,
    value: str,
    pos: tuple[int, int],
    size: int = 22,
    color: tuple[int, int, int] | None = None,
    bold: bool = False,
    center: bool = False,
) -> pygame.Rect:
    rendered = render_text(value, size, color or palette().text, bold=bold)
    rect = rendered.get_rect(center=pos) if center else rendered.get_rect(topleft=pos)
    surface.blit(rendered, rect)
    return rect


def glass_card(
    surface: pygame.Surface,
    rect: pygame.Rect,
    *,
    tint: tuple[int, int, int] | None = None,
    radius: int = 20,
    alpha: int = 205,
    stroke: bool = False,
) -> None:
    assert _tokens is not None
    layer = pygame.Surface(rect.size, pygame.SRCALPHA)
    pygame.draw.rect(
        layer,
        (*(tint or palette().surface), alpha),
        layer.get_rect(),
        border_radius=radius,
    )
    surface.blit(layer, rect)
    if stroke:
        pygame.draw.rect(surface, (*_tokens.stroke, 160), rect, width=1, border_radius=radius)


def button(
    surface: pygame.Surface,
    rect: pygame.Rect,
    label: str,
    active: bool = False,
    color: tuple[int, int, int] | None = None,
    compact: bool = False,
) -> None:
    fill = color or (palette().accent if active else palette().surface_alt)
    glass_card(surface, rect, tint=fill, radius=14, alpha=255)
    label_color = (255, 255, 255) if active or color is not None else palette().text
    text(surface, label, rect.center, 15 if compact else 17, label_color, bold=True, center=True)


def header(surface: pygame.Surface, title: str, subtitle: str = "", icon_name: str = "") -> None:
    x = 16
    if icon_name:
        icon(surface, icon_name, (16, 34), 26, palette().accent)
        x = 54
    text(surface, title, (x, 31), 23, palette().text, bold=True)
    if subtitle:
        text(surface, subtitle, (x, 58), 14, palette().muted)


def icon(
    surface: pygame.Surface,
    name: str,
    pos: tuple[int, int],
    size: int,
    color: tuple[int, int, int] | None = None,
    *,
    center: bool = False,
) -> pygame.Rect:
    center_pos = pos if center else (pos[0] + size // 2, pos[1] + size // 2)
    components.icon(surface, name, center_pos, size, color or palette().text)
    return pygame.Rect(0, 0, size, size).move(center_pos[0] - size // 2, center_pos[1] - size // 2)


def modal(
    surface: pygame.Surface,
    title: str,
    body: str,
    *,
    color: tuple[int, int, int] | None = None,
    persistent: bool = False,
) -> None:
    shade = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
    shade.fill((0, 0, 0, 155))
    surface.blit(shade, (0, 0))
    panel = pygame.Rect(40, 136, 400, 182)
    glass_card(surface, panel, tint=palette().surface, radius=26, alpha=245)
    accent = color or palette().accent
    pygame.draw.circle(surface, accent, (240, 169), 8)
    text(surface, title, (240, 194), 24, accent, bold=True, center=True)
    lines = wrap_text(body, 16, 350)[:2]
    for index, line in enumerate(lines):
        text(surface, line, (240, 231 + index * 23), 16, palette().text, center=True)
    if persistent:
        text(surface, "轻触任意位置继续", (240, 293), 14, palette().muted, center=True)
