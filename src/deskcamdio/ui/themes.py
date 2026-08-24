"""Shared theme tokens for the Fish aquarium interface."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ThemeTokens:
    id: str
    name: str
    background: tuple[int, int, int]
    surface: tuple[int, int, int]
    surface_elevated: tuple[int, int, int]
    text_primary: tuple[int, int, int]
    text_secondary: tuple[int, int, int]
    accent: tuple[int, int, int]
    danger: tuple[int, int, int]
    warning: tuple[int, int, int]
    stroke: tuple[int, int, int]
    shadow_alpha: int
    background_top: tuple[int, int, int]
    background_bottom: tuple[int, int, int]
    water: tuple[int, int, int]
    sand: tuple[int, int, int]


FISH = ThemeTokens(
    id="fish",
    name="锦鲤红",
    background=(12, 14, 18),
    surface=(26, 30, 38),
    surface_elevated=(38, 44, 54),
    text_primary=(240, 242, 245),
    text_secondary=(158, 166, 178),
    accent=(226, 68, 68),
    danger=(226, 68, 68),
    warning=(240, 165, 44),
    stroke=(52, 58, 70),
    shadow_alpha=90,
    background_top=(31, 35, 44),
    background_bottom=(12, 14, 18),
    water=(77, 109, 143),
    sand=(126, 94, 73),
)

AQUATIC = ThemeTokens(
    id="aquatic",
    name="水族蓝灰",
    background=(238, 243, 248),
    surface=(255, 255, 255),
    surface_elevated=(246, 250, 253),
    text_primary=(28, 36, 48),
    text_secondary=(108, 122, 140),
    accent=(32, 118, 196),
    danger=(206, 62, 58),
    warning=(222, 148, 34),
    stroke=(210, 220, 230),
    shadow_alpha=40,
    background_top=(230, 243, 252),
    background_bottom=(193, 218, 233),
    water=(174, 216, 241),
    sand=(178, 137, 92),
)

CREAM = ThemeTokens(
    id="cream",
    name="暖日奶油",
    background=(249, 243, 232),
    surface=(255, 252, 245),
    surface_elevated=(253, 247, 236),
    text_primary=(62, 50, 40),
    text_secondary=(146, 128, 110),
    accent=(226, 122, 46),
    danger=(200, 72, 60),
    warning=(214, 150, 40),
    stroke=(228, 216, 198),
    shadow_alpha=45,
    background_top=(255, 251, 244),
    background_bottom=(246, 226, 201),
    water=(187, 221, 228),
    sand=(190, 145, 96),
)

GRAPHITE = ThemeTokens(
    id="graphite",
    name="石墨黑",
    background=(16, 17, 20),
    surface=(28, 30, 35),
    surface_elevated=(40, 43, 50),
    text_primary=(228, 231, 236),
    text_secondary=(176, 180, 194),
    accent=(122, 132, 232),
    danger=(214, 78, 78),
    warning=(226, 168, 62),
    stroke=(56, 60, 70),
    shadow_alpha=80,
    background_top=(39, 43, 53),
    background_bottom=(16, 17, 20),
    water=(53, 75, 105),
    sand=(91, 75, 68),
)

THEMES: dict[str, ThemeTokens] = {t.id: t for t in (FISH, AQUATIC, CREAM, GRAPHITE)}

DEFAULT_THEME_ID = "aquatic"


class ThemeService:
    """Holds the active palette; persistence lives in StateStore settings."""

    def __init__(self, theme_id: str = DEFAULT_THEME_ID) -> None:
        self._tokens = THEMES.get(theme_id, THEMES[DEFAULT_THEME_ID])

    @property
    def tokens(self) -> ThemeTokens:
        return self._tokens

    def select(self, theme_id: str) -> None:
        if theme_id not in THEMES:
            raise ValueError(f"Unknown theme {theme_id}")
        self._tokens = THEMES[theme_id]
