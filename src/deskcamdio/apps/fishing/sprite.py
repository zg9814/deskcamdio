from __future__ import annotations

from dataclasses import dataclass
from importlib.resources import files

import pygame

_FISH_SHEET: pygame.Surface | None = None


@dataclass(frozen=True, slots=True)
class AnimationClip:
    row: int
    fps: float
    loop: bool = True
    frames: int = 4


FISH_CLIPS = {
    "idle": AnimationClip(0, 6),
    "swim": AnimationClip(1, 8),
    "death": AnimationClip(6, 8, loop=False),
    "attack": AnimationClip(7, 10, loop=False),
}


class SpriteSheetAnimator:
    """Small fixed-grid sprite animator with nearest-neighbour scaling."""

    def __init__(
        self,
        sheet: pygame.Surface,
        clips: dict[str, AnimationClip],
        *,
        frame_size: tuple[int, int] = (64, 64),
        color_index: int = 0,
        color_columns: int = 4,
        animation_rows: int = 8,
    ) -> None:
        self.sheet = sheet
        self.clips = clips
        self.frame_width, self.frame_height = frame_size
        self.color_index = color_index
        self.color_columns = color_columns
        self.animation_rows = animation_rows
        self.clip_name = next(iter(clips))
        self.elapsed = 0.0
        self._cache: dict[tuple[str, int, tuple[int, int], bool], pygame.Surface] = {}

    @classmethod
    def fish(cls, color_index: int = 0) -> SpriteSheetAnimator:
        global _FISH_SHEET
        if _FISH_SHEET is None:
            asset = files("deskcamdio.assets.fish").joinpath("fish_sprite_sheet_64.png")
            with asset.open("rb") as stream:
                loaded = pygame.image.load(stream, "fish_sprite_sheet_64.png")
            _FISH_SHEET = (
                loaded.convert_alpha() if pygame.display.get_surface() is not None else loaded
            )
        return cls(_FISH_SHEET, FISH_CLIPS, color_index=color_index)

    def set_clip(self, name: str, *, restart: bool = False) -> None:
        if name not in self.clips:
            raise KeyError(f"Unknown animation clip: {name}")
        if name != self.clip_name or restart:
            self.clip_name = name
            self.elapsed = 0.0

    def clear_cache(self) -> None:
        self._cache.clear()

    def update(self, delta_seconds: float) -> None:
        self.elapsed += max(0.0, delta_seconds)

    @property
    def frame_index(self) -> int:
        clip = self.clips[self.clip_name]
        raw = int(self.elapsed * clip.fps)
        return raw % clip.frames if clip.loop else min(raw, clip.frames - 1)

    def frame(self, size: tuple[int, int], *, flip_x: bool = False) -> pygame.Surface:
        index = self.frame_index
        key = (self.clip_name, index, size, flip_x)
        if key in self._cache:
            return self._cache[key]
        clip = self.clips[self.clip_name]
        group_x = self.color_index % self.color_columns
        group_y = self.color_index // self.color_columns
        source = pygame.Rect(
            (group_x * 4 + index) * self.frame_width,
            (group_y * self.animation_rows + clip.row) * self.frame_height,
            self.frame_width,
            self.frame_height,
        )
        image = self.sheet.subsurface(source).copy()
        image = pygame.transform.scale(image, size)
        if flip_x:
            image = pygame.transform.flip(image, True, False)
        self._cache[key] = image
        return image
