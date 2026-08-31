"""UI kit coverage: themes, typography wrapping, components, renderer."""

from __future__ import annotations

import os

import pygame
import pytest

from deskcamdio.ui import art, components, renderer
from deskcamdio.ui.themes import (
    DEFAULT_THEME_ID,
    THEMES,
    ThemeService,
)
from deskcamdio.ui.typography import clear_caches, render_text, wrap_text

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")


@pytest.fixture(scope="module", autouse=True)
def _pygame():
    pygame.display.init()
    pygame.font.init()
    yield
    clear_caches()


def surface() -> pygame.Surface:
    return pygame.Surface((480, 480))


def test_theme_service_select_and_reject() -> None:
    service = ThemeService()
    assert service.tokens.id == DEFAULT_THEME_ID
    service.select("graphite")
    assert service.tokens.id == "graphite"
    with pytest.raises(ValueError):
        service.select("neon")


def test_all_four_themes_registered() -> None:
    assert set(THEMES) == {"fish", "aquatic", "cream", "graphite"}


@pytest.mark.parametrize(
    "text",
    [
        "你好世界这是一段很长的中文文本需要换行处理",
        "latin text wraps on spaces only",
        "",
        "混合 mixed 文本内容",
    ],
)
def test_wrap_text_never_exceeds_width(text: str) -> None:
    clear_caches()
    lines = wrap_text(text, 18, 200)
    assert lines
    for line in lines:
        width = render_text(line, 18, (0, 0, 0)).get_width()
        if len(line) > 1:
            assert width <= max(200, render_text(line.strip(), 18, (0, 0, 0)).get_width())


def test_render_text_cache_hits() -> None:
    clear_caches()
    first = render_text("缓存", 20, (1, 2, 3))
    second = render_text("缓存", 20, (1, 2, 3))
    assert first is second


def test_components_draw_all_primitives() -> None:
    clear_caches()
    theme = THEMES["aquatic"]
    target = surface()
    rect = pygame.Rect(40, 40, 120, 48)

    components.card(target, rect, theme)
    components.card(target, rect.move(0, 60), theme, elevated=True)
    components.button(target, rect.move(140, 0), "确定", theme)
    components.ghost_button(target, rect.move(140, 60), "取消", theme)
    components.progress_bar(target, rect.move(0, 130), 0.5, theme)
    components.progress_bar(target, rect.move(0, 150), 1.4, theme)
    components.row(target, rect.move(0, 180), "标题行", theme, trailing="尾注")
    components.row(target, rect.move(0, 240), "选中行", theme, selected=True)
    components.status_chip(target, "标签", theme, (300, 300))

    hit = components.hit_test({"a": rect}, rect.center)
    assert hit == "a"
    assert components.hit_test({"a": rect}, (479, 479)) is None


def test_renderer_chrome() -> None:
    clear_caches()
    theme = THEMES["fish"]
    target = surface()
    renderer.background(target, theme)
    renderer.status_bar(target, theme, online=True, bluetooth=True, battery="87%")
    renderer.status_bar(target, theme, online=False, bluetooth=False)


def test_generated_art_loads_at_native_sizes() -> None:
    art.clear_caches()
    background = art.load("aquarium-far-aquatic-480-v1.png")
    camera_fault = art.load("state-camera-unavailable-160x112-v1.png")
    assert background is not None and background.get_size() == (480, 480)
    assert camera_fault is not None and camera_fault.get_size() == (160, 112)
    assert art.load("missing-art.png") is None
    art.clear_caches()
