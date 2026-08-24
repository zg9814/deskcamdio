"""Bounded sprite animation helpers used by the aquarium home."""

from __future__ import annotations

from dataclasses import dataclass
from importlib.resources import files

import pygame


@dataclass(frozen=True, slots=True)
class AnimationClip:
    row: int
    fps: float
    loop: bool = True
    frames: int = 4


FISH_CLIPS = {
    "idle": AnimationClip(0, 6),
    "swim": AnimationClip(1, 8),
    "death": AnimationClip(6, 8, False),
    "attack": AnimationClip(7, 10, False),
}
_SHEET: pygame.Surface | None = None


class FishAnimator:
    def __init__(self, color_index: int = 0) -> None:
        global _SHEET
        if _SHEET is None:
            path = files("deskcamdio.assets.fish").joinpath("fish_sprite_sheet_64.png")
            with path.open("rb") as stream:
                loaded = pygame.image.load(stream, "fish_sprite_sheet_64.png")
            _SHEET = loaded.convert_alpha() if pygame.display.get_surface() else loaded
        self.sheet = _SHEET
        self.color_index = color_index
        self.clip_name = "swim"
        self.elapsed = 0.0
        self._cache: dict[tuple[str, int, tuple[int, int], bool], pygame.Surface] = {}

    def set_clip(self, name: str, *, restart: bool = False) -> None:
        if name not in FISH_CLIPS:
            raise KeyError(name)
        if restart or name != self.clip_name:
            self.clip_name = name
            self.elapsed = 0.0

    def update(self, delta: float) -> None:
        self.elapsed += max(0.0, delta)

    def frame(self, size: tuple[int, int], *, flip_x: bool = False) -> pygame.Surface:
        clip = FISH_CLIPS[self.clip_name]
        raw = int(self.elapsed * clip.fps)
        index = raw % clip.frames if clip.loop else min(raw, clip.frames - 1)
        key = (self.clip_name, index, size, flip_x)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        group_x = self.color_index % 4
        group_y = self.color_index // 4
        source = pygame.Rect((group_x * 4 + index) * 64, (group_y * 8 + clip.row) * 64, 64, 64)
        image = pygame.transform.scale(self.sheet.subsurface(source), size)
        if flip_x:
            image = pygame.transform.flip(image, True, False)
        if len(self._cache) >= 32:
            self._cache.clear()
        self._cache[key] = image
        return image

    def clear(self) -> None:
        self._cache.clear()
