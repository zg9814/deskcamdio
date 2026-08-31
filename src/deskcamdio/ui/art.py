"""Lazy loader for generated UI artwork.

Only assets used by the active page are decoded. Scaled variants are bounded so
the Raspberry Pi Zero 2 W does not retain an unbounded surface cache.
"""

from __future__ import annotations

from importlib.resources import files

import pygame

_SURFACES: dict[str, pygame.Surface | None] = {}
_SCALED: dict[tuple[str, tuple[int, int]], pygame.Surface] = {}
_MAX_SCALED = 32


def load(name: str) -> pygame.Surface | None:
    """Load one packaged PNG, returning ``None`` when an optional asset is absent."""

    if name in _SURFACES:
        return _SURFACES[name]
    try:
        resource = files("deskcamdio.assets.art").joinpath(name)
        with resource.open("rb") as stream:
            loaded = pygame.image.load(stream, name)
        if pygame.display.get_surface() is not None:
            surface = (
                loaded.convert_alpha()
                if loaded.get_flags() & pygame.SRCALPHA
                else loaded.convert()
            )
        else:
            surface = loaded
    except (FileNotFoundError, ModuleNotFoundError, pygame.error):
        surface = None
    _SURFACES[name] = surface
    return surface


def get(name: str, size: tuple[int, int] | None = None) -> pygame.Surface | None:
    """Return an original or nearest-neighbour scaled artwork surface."""

    source = load(name)
    if source is None or size is None or source.get_size() == size:
        return source
    key = (name, size)
    cached = _SCALED.get(key)
    if cached is not None:
        return cached
    if len(_SCALED) >= _MAX_SCALED:
        _SCALED.clear()
    cached = pygame.transform.scale(source, size)
    _SCALED[key] = cached
    return cached


def blit_centered(
    target: pygame.Surface,
    name: str,
    center: tuple[int, int],
    size: tuple[int, int] | None = None,
) -> pygame.Rect | None:
    """Blit an asset centered at ``center`` and return the occupied rectangle."""

    image = get(name, size)
    if image is None:
        return None
    rect = image.get_rect(center=center)
    target.blit(image, rect)
    return rect


def clear_caches() -> None:
    _SURFACES.clear()
    _SCALED.clear()
