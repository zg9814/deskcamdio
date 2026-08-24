"""AudioService: mixer ownership, ducking rules and local music playback."""

from __future__ import annotations

import contextlib
import logging
from pathlib import Path
from typing import Any

import pygame

LOGGER = logging.getLogger(__name__)

ASSETS_ROOT = Path(__file__).resolve().parents[1] / "assets" / "sounds"
UI_DUCK_FACTOR = 0.28
SOUND_CACHE_LIMIT = 32


class AudioService:
    """Owns the pygame mixer, sound cache and local music channel.

    Ducking rule (guide §10 音乐): while music plays, ordinary UI taps drop to
    28% volume; alarms, errors and the shutter keep full level.
    """

    FULL_VOLUME_CATEGORIES = frozenset({"alarm", "error", "shutter"})

    def __init__(self, assets_root: Path | None = None) -> None:
        self.assets_root = assets_root or ASSETS_ROOT
        self._mixer_open = False
        self._sounds: dict[str, pygame.mixer.Sound] = {}
        self._music_playing = False
        self._music_path: Path | None = None
        self.volume_percent = 80
        self._mixer_warning_emitted = False

    # ---- volume ------------------------------------------------------------

    def set_volume(self, percent: int) -> None:
        self.volume_percent = max(0, min(100, int(percent)))
        if pygame.mixer.get_init():
            pygame.mixer.music.set_volume(self.volume_percent / 100)

    def load_volume(self, percent: int) -> None:
        self.volume_percent = max(0, min(100, int(percent)))
        self.set_volume(self.volume_percent)

    # ---- mixer -----------------------------------------------------------

    def open_mixer(self) -> None:
        if not pygame.mixer.get_init():
            pygame.mixer.init(frequency=48_000, size=-16, channels=2, buffer=4096)
        self._mixer_open = True

    def _ensure_mixer(self) -> bool:
        if self._mixer_open and pygame.mixer.get_init():
            return True
        try:
            self.open_mixer()
            self.set_volume(self.volume_percent)
            return True
        except pygame.error:
            if not self._mixer_warning_emitted:
                LOGGER.warning("audio mixer unavailable; continuing silently")
                self._mixer_warning_emitted = True
            return False

    def close(self) -> None:
        if pygame.mixer.get_init():
            with contextlib.suppress(pygame.error):
                pygame.mixer.music.stop()
            pygame.mixer.quit()
        self._mixer_open = False
        self._sounds.clear()

    @property
    def music_playing(self) -> bool:
        if self._music_path is None:
            return False
        return bool(pygame.mixer.get_init()) and pygame.mixer.music.get_busy()

    # ---- sounds ------------------------------------------------------------

    def play_sound(self, name: str, category: str = "ui") -> None:
        if not self._ensure_mixer():
            return
        sound = self._load(name)
        if sound is None:
            return
        factor = 1.0
        if category not in self.FULL_VOLUME_CATEGORIES and self.music_playing:
            factor = UI_DUCK_FACTOR
        sound.set_volume(factor)
        sound.play()

    def _load(self, name: str) -> pygame.mixer.Sound | None:
        if name in self._sounds:
            return self._sounds[name]
        for suffix in (".ogg", ".wav"):
            path = self.assets_root / f"{name}{suffix}"
            if path.exists():
                try:
                    sound = pygame.mixer.Sound(str(path))
                except pygame.error:
                    LOGGER.warning("sound %s failed to decode", path.name)
                    return None
                if len(self._sounds) >= SOUND_CACHE_LIMIT:
                    self._sounds.pop(next(iter(self._sounds)))
                self._sounds[name] = sound
                return sound
        return None

    # ---- local music -------------------------------------------------------

    def play_music(self, path: Path) -> bool:
        if not self._ensure_mixer():
            return False
        try:
            pygame.mixer.music.load(str(path))
            pygame.mixer.music.play()
        except pygame.error:
            LOGGER.warning("cannot play %s", path.name)
            return False
        self._music_path = path
        self._music_playing = True
        return True

    def stop_music(self) -> None:
        if pygame.mixer.get_init():
            pygame.mixer.music.stop()
        self._music_playing = False
        self._music_path = None

    def pause_music(self) -> None:
        if pygame.mixer.get_init():
            pygame.mixer.music.pause()
            self._music_playing = False

    def resume_music(self) -> None:
        if pygame.mixer.get_init() and self._music_path is not None:
            pygame.mixer.music.unpause()
            self._music_playing = True

    def poll_music_finished(self) -> bool:
        """True exactly once when the loaded track ran to completion."""
        if self._music_path is None or not self._music_playing:
            return False
        if self._mixer_open and pygame.mixer.get_init() and pygame.mixer.music.get_busy():
            return False
        self._music_playing = False
        return True

    def now_playing(self) -> dict[str, Any] | None:
        if self._music_path is None:
            return None
        return {"path": str(self._music_path), "title": self._music_path.stem}
