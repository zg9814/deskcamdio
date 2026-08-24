"""Reusable drawing components: cards, buttons, list rows, progress bars."""

from __future__ import annotations

from collections import OrderedDict
from importlib.resources import files

import pygame

from deskcamdio.ui.themes import ThemeTokens
from deskcamdio.ui.typography import render_text, wrap_text

_ICON_CACHE: OrderedDict[tuple[str, int, tuple[int, int, int]], pygame.Surface] = OrderedDict()


def card(
    surface: pygame.Surface,
    rect: pygame.Rect,
    theme: ThemeTokens,
    *,
    elevated: bool = False,
    radius: int = 16,
) -> None:
    color = theme.surface_elevated if elevated else theme.surface
    pygame.draw.rect(surface, color, rect, border_radius=radius)
    pygame.draw.rect(surface, theme.stroke, rect, width=1, border_radius=radius)


def glass_card(
    surface: pygame.Surface,
    rect: pygame.Rect,
    theme: ThemeTokens,
    *,
    alpha: int = 220,
    radius: int = 18,
) -> None:
    layer = pygame.Surface(rect.size, pygame.SRCALPHA)
    pygame.draw.rect(layer, (*theme.surface, alpha), layer.get_rect(), border_radius=radius)
    surface.blit(layer, rect)
    pygame.draw.rect(surface, (*theme.stroke, 180), rect, 1, border_radius=radius)


def button(
    surface: pygame.Surface,
    rect: pygame.Rect,
    label: str,
    theme: ThemeTokens,
    *,
    size: int = 18,
    pressed: bool = False,
) -> None:
    fill = theme.accent if not pressed else theme.text_secondary
    pygame.draw.rect(surface, fill, rect, border_radius=max(10, rect.height // 3))
    label_surface = render_text(label, size, (255, 255, 255), bold=True)
    surface.blit(label_surface, label_surface.get_rect(center=rect.center))


def ghost_button(
    surface: pygame.Surface,
    rect: pygame.Rect,
    label: str,
    theme: ThemeTokens,
    *,
    size: int = 17,
) -> None:
    pygame.draw.rect(surface, theme.surface, rect, border_radius=max(10, rect.height // 3))
    pygame.draw.rect(surface, theme.stroke, rect, width=1, border_radius=max(10, rect.height // 3))
    label_surface = render_text(label, size, theme.text_primary)
    surface.blit(label_surface, label_surface.get_rect(center=rect.center))


def hit_test(buttons: dict[str, pygame.Rect], pos: tuple[int, int]) -> str | None:
    for name, rect in buttons.items():
        if rect.collidepoint(pos):
            return name
    return None


def progress_bar(
    surface: pygame.Surface,
    rect: pygame.Rect,
    ratio: float,
    theme: ThemeTokens,
) -> None:
    ratio = max(0.0, min(1.0, ratio))
    pygame.draw.rect(surface, theme.surface_elevated, rect, border_radius=rect.height // 2)
    if ratio > 0:
        inner = rect.copy()
        inner.width = max(rect.height, int(rect.width * ratio))
        pygame.draw.rect(surface, theme.accent, inner, border_radius=rect.height // 2)


def row(
    surface: pygame.Surface,
    rect: pygame.Rect,
    title: str,
    theme: ThemeTokens,
    *,
    trailing: str = "",
    selected: bool = False,
    size: int = 19,
) -> None:
    fill = theme.surface_elevated if selected else theme.surface
    pygame.draw.rect(surface, fill, rect, border_radius=12)
    title_width = rect.width - (112 if trailing else 28)
    title_lines = wrap_text(title, size, title_width)[:2]
    rendered_lines = [render_text(line, size, theme.text_primary) for line in title_lines]
    total_height = sum(line.get_height() for line in rendered_lines)
    y = rect.y + max(2, (rect.height - total_height) // 2)
    for title_surface in rendered_lines:
        surface.blit(title_surface, (rect.x + 14, y))
        y += title_surface.get_height()
    if trailing:
        trail = render_text(trailing, size - 4, theme.text_secondary)
        surface.blit(
            trail,
            (rect.right - trail.get_width() - 14, rect.y + (rect.height - trail.get_height()) // 2),
        )


def status_chip(
    surface: pygame.Surface, text: str, theme: ThemeTokens, pos: tuple[int, int]
) -> None:
    rendered = render_text(text, 14, theme.text_secondary)
    chip_rect = rendered.get_rect(midleft=pos)
    pygame.draw.rect(surface, theme.surface, chip_rect.inflate(12, 6), border_radius=9)
    surface.blit(rendered, chip_rect)


def icon(
    surface: pygame.Surface,
    name: str,
    center: tuple[int, int],
    size: int,
    color: tuple[int, int, int],
) -> None:
    key = (name, size, color)
    image = _ICON_CACHE.get(key)
    if image is None:
        try:
            path = files("deskcamdio.assets.icons").joinpath(f"{name}.png")
            with path.open("rb") as stream:
                mask = pygame.image.load(stream, f"{name}.png").convert_alpha()
            mask = pygame.transform.smoothscale(mask, (size, size))
            image = pygame.Surface((size, size), pygame.SRCALPHA)
            image.fill((*color, 255))
            image.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
        except (FileNotFoundError, ModuleNotFoundError, pygame.error):
            image = pygame.Surface((size, size), pygame.SRCALPHA)
            pygame.draw.circle(image, color, image.get_rect().center, size // 3, 2)
        if len(_ICON_CACHE) >= 64:
            _ICON_CACHE.popitem(last=False)
        _ICON_CACHE[key] = image
    else:
        _ICON_CACHE.move_to_end(key)
    surface.blit(image, image.get_rect(center=center))


def page_dots(
    surface: pygame.Surface, page: int, count: int, theme: ThemeTokens, y: int = 462
) -> None:
    start = 240 - ((count - 1) * 16) // 2
    for index in range(count):
        color = theme.accent if index == page else theme.stroke
        pygame.draw.circle(surface, color, (start + index * 16, y), 4)


def clear_caches() -> None:
    _ICON_CACHE.clear()
