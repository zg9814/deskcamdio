from __future__ import annotations

from pathlib import Path

import pygame
import pytest

from deskcamdio.services import audio as audio_mod
from deskcamdio.services.audio import AudioService


@pytest.fixture()
def audio() -> AudioService:
    import os

    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    if not pygame.display.get_init():
        pygame.display.init()
    service = AudioService()
    service.open_mixer()
    yield service
    service.close()


def _wav(path: Path) -> Path:
    import wave

    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        handle.writeframes(b"\x00\x00" * 800)
    return path


def test_play_sound_ducks_ui_but_not_alarm(audio: AudioService, tmp_path: Path) -> None:
    sounds = tmp_path / "sounds"
    sounds.mkdir()
    track = audio.play_music(_wav(tmp_path / "m.wav"))
    assert track is True

    (sounds / "tap.wav").parent.mkdir(exist_ok=True)
    audio.assets_root = tmp_path / "sounds"
    _wav(audio.assets_root / "tap.wav")

    audio.play_sound("tap", category="ui")
    assert audio._sounds["tap"].get_volume() == pytest.approx(0.28, abs=0.01)

    _wav(audio.assets_root / "shutter.wav")
    audio.play_sound("shutter", category="shutter")
    assert audio._sounds["shutter"].get_volume() == pytest.approx(1.0)


def test_sound_cache_eviction(audio: AudioService, tmp_path: Path) -> None:
    monkey_target = audio
    monkey_target.assets_root = tmp_path / "s"
    monkey_target.assets_root.mkdir()
    for index in range(audio_mod.SOUND_CACHE_LIMIT + 2):
        name = f"s{index}"
        _wav(monkey_target.assets_root / f"{name}.wav")
        audio.play_sound(name)
    assert len(audio._sounds) <= audio_mod.SOUND_CACHE_LIMIT


def test_music_lazily_opens_mixer(tmp_path: Path) -> None:
    closed = AudioService()
    assert closed.play_music(_wav(tmp_path / "x.wav")) is True
    assert pygame.mixer.get_init() is not None
    closed.close()


def test_pause_resume_without_music_is_safe(audio: AudioService) -> None:
    audio.pause_music()
    audio.resume_music()
    audio.poll_music_finished()
    assert audio.now_playing() is None
