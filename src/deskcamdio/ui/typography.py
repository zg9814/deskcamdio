"""Typography: cached fonts, CJK-aware wrapping, text LRU (≤512 entries)."""

from __future__ import annotations

import logging
from collections import OrderedDict
from pathlib import Path

import pygame
import pygame.freetype

LOGGER = logging.getLogger(__name__)

_FONT_CACHE_LIMIT = 512
_TEXT_CACHE: OrderedDict[tuple, pygame.Surface] = OrderedDict()
_FONT_SIZES: dict[int, _FontView] = {}
_SHARED_FONT: pygame.freetype.Font | None = None
_LATIN_FONT: pygame.freetype.Font | None = None
_asset_font: Path | None = None
_asset_probe_done = False

CJK_RANGES = (
    (0x2E80, 0x9FFF),
    (0xF900, 0xFAFF),
    (0xFF00, 0xFFEF),
    (0x3000, 0x303F),
)


def _is_cjk(char: str) -> bool:
    code = ord(char)
    return any(lo <= code <= hi for lo, hi in CJK_RANGES)


class _FontView:
    """pygame.font-compatible sized view over one shared FreeType face."""

    def __init__(self, size: int) -> None:
        self.size_px = size

    def render(self, text: str, antialias: bool, color: tuple[int, int, int]) -> pygame.Surface:
        del antialias
        rendered: list[tuple[pygame.Surface, int]] = []
        for value, face in _font_runs(text):
            surface, _rect = face.render(value, fgcolor=color, size=self.size_px)
            advance = max(surface.width, face.get_rect(value, size=self.size_px).width)
            rendered.append((surface, advance))
        width = sum(advance for _surface, advance in rendered)
        height = max((surface.height for surface, _advance in rendered), default=1)
        output = pygame.Surface((max(1, width), max(1, height)), pygame.SRCALPHA)
        x = 0
        for surface, advance in rendered:
            output.blit(surface, (x, height - surface.height))
            x += advance
        return output

    def size(self, text: str) -> tuple[int, int]:
        rects = [face.get_rect(value, size=self.size_px) for value, face in _font_runs(text)]
        return sum(rect.width for rect in rects), max((rect.height for rect in rects), default=1)

    def get_linesize(self) -> int:
        return max(
            int(_shared_font().get_sized_height(self.size_px)),
            int(_latin_font().get_sized_height(self.size_px)),
        )

    def get_height(self) -> int:
        return self.get_linesize()


def _shared_font() -> pygame.freetype.Font:
    global _SHARED_FONT
    if _SHARED_FONT is not None and pygame.freetype.get_init():
        return _SHARED_FONT
    _SHARED_FONT = None
    if not pygame.freetype.get_init():
        pygame.freetype.init()
    _SHARED_FONT = pygame.freetype.Font(str(_asset_font) if _asset_font is not None else None)
    return _SHARED_FONT


def _latin_font() -> pygame.freetype.Font:
    global _LATIN_FONT
    if _LATIN_FONT is not None and pygame.freetype.get_init():
        return _LATIN_FONT
    if not pygame.freetype.get_init():
        pygame.freetype.init()
    _LATIN_FONT = pygame.freetype.Font(None)
    return _LATIN_FONT


def _font_runs(text: str) -> list[tuple[str, pygame.freetype.Font]]:
    if not text:
        return [("", _latin_font())]
    runs: list[tuple[str, pygame.freetype.Font]] = []
    current = ""
    current_is_cjk = _is_cjk(text[0])
    for char in text:
        char_is_cjk = _is_cjk(char)
        if current and char_is_cjk != current_is_cjk:
            runs.append((current, _shared_font() if current_is_cjk else _latin_font()))
            current = ""
        current += char
        current_is_cjk = char_is_cjk
    runs.append((current, _shared_font() if current_is_cjk else _latin_font()))
    return runs


def font(size: int) -> _FontView:
    """Return a light sized view backed by one shared CJK font face."""
    global _asset_font, _asset_probe_done, _SHARED_FONT, _LATIN_FONT
    if not _asset_probe_done:
        _asset_probe_done = True
        load_asset_fonts_if_present()
    cached = _FONT_SIZES.get(size)
    if cached is not None:
        try:
            cached.get_height()
            return cached
        except pygame.error:
            # Font objects die when the font module quits somewhere else.
            _FONT_SIZES.clear()
            _TEXT_CACHE.clear()
            _SHARED_FONT = None
            _LATIN_FONT = None
    fresh = _FontView(size)
    _FONT_SIZES[size] = fresh
    return fresh


def clear_caches() -> None:
    """Theme switches call this to drop colour-tinted surfaces."""
    _TEXT_CACHE.clear()


def render_text(
    text: str,
    size: int,
    color: tuple[int, int, int],
    *,
    bold: bool = False,
) -> pygame.Surface:
    key = (text, size, color, bold)
    cached = _TEXT_CACHE.get(key)
    if cached is not None:
        _TEXT_CACHE.move_to_end(key)
        return cached
    try:
        surface = _render_surface(text, size, color)
    except pygame.error:
        # A pygame.quit()/re-init cycle somewhere invalidated our cached
        # objects; rebuild everything once and retry.
        clear_caches()
        _FONT_SIZES.clear()
        global _SHARED_FONT, _LATIN_FONT
        _SHARED_FONT = None
        _LATIN_FONT = None
        surface = _render_surface(text, size, color)
    _TEXT_CACHE[key] = surface
    while len(_TEXT_CACHE) > _FONT_CACHE_LIMIT:
        _TEXT_CACHE.popitem(last=False)
    return surface


def _render_surface(text: str, size: int, color: tuple[int, int, int]) -> pygame.Surface:
    return font(size).render(text, True, color)


def wrap_text(text: str, size: int, max_width: int) -> list[str]:
    """Wrap for body/lyrics; break anywhere inside CJK runs."""
    if not text:
        return [""]
    measure = font(size)
    lines: list[str] = []
    for paragraph in text.split("\n"):
        current = ""
        for char in paragraph:
            candidate = current + char
            if _is_cjk(char):
                if measure.size(candidate)[0] <= max_width or not current:
                    current = candidate
                else:
                    lines.append(current)
                    current = char
            else:
                if " " in candidate or measure.size(candidate)[0] <= max_width:
                    if measure.size(candidate)[0] <= max_width:
                        current = candidate
                    elif not current:
                        current = char
                    else:
                        stripped = current.rstrip(" ")
                        lines.append(stripped)
                        current = char.lstrip(" ")
                else:
                    lines.append(current)
                    current = char.lstrip(" ")
        lines.append(current)
    return lines


def draw_wrapped(
    surface: pygame.Surface,
    text: str,
    rect: pygame.Rect,
    size: int,
    color: tuple[int, int, int],
    line_gap: int = 4,
) -> int:
    y = rect.y
    line_height = font(size).get_linesize() + line_gap
    max_lines = max(1, rect.height // max(1, line_height))
    for line in wrap_text(text, size, rect.width)[:max_lines]:
        rendered = render_text(line, size, color)
        surface.blit(rendered, (rect.x, y))
        y += rendered.get_height() + line_gap
    return y


def asset_font_path() -> Path | None:
    fonts_dir = Path(__file__).resolve().parents[1] / "assets" / "fonts"
    for pattern in ("*.ttf", "*.otf"):
        found = sorted(fonts_dir.glob(pattern))
        if found:
            return found[0]
    return None


def load_asset_fonts_if_present() -> bool:
    """Activate the bundled CJK font; returns True when one was found."""
    global _asset_font, _SHARED_FONT, _LATIN_FONT
    path = asset_font_path()
    if path is None:
        LOGGER.debug("no bundled font; using pygame default")
        return False
    _asset_font = path
    _SHARED_FONT = None
    _LATIN_FONT = None
    _FONT_SIZES.clear()
    _TEXT_CACHE.clear()
    LOGGER.info("event=asset_font_loaded file=%s", path.name)
    return True
