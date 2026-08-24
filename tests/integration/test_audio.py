from __future__ import annotations

import os
from pathlib import Path

import pygame
import pytest

from deskcamdio.services.audio import AudioService


@pytest.fixture()
def audio() -> AudioService:
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    if not pygame.display.get_init():
        pygame.display.init()
    service = AudioService()
    service.open_mixer()
    yield service
    service.close()


def test_mixer_opens_and_closes(audio: AudioService) -> None:
    assert pygame.mixer.get_init() is not None
    audio.close()
    assert pygame.mixer.get_init() is None


def test_missing_sound_is_silent_noop(audio: AudioService) -> None:
    audio.play_sound("does-not-exist")  # must not raise


def test_local_music_lifecycle(audio: AudioService, tmp_path: Path) -> None:
    track = tmp_path / "song.wav"
    _write_wav(track, seconds=0.3)
    assert audio.play_music(track) is True
    assert audio.now_playing() is not None
    assert audio.now_playing()["title"] == "song"

    audio.pause_music()
    assert audio.music_playing is False
    audio.resume_music()

    finished = False
    for _ in range(120):
        if audio.poll_music_finished():
            finished = True
            break
        import time

        time.sleep(0.05)
    assert finished, "track should complete and report once"
    assert audio.poll_music_finished() is False  # only once

    audio.stop_music()
    assert audio.now_playing() is None


def test_play_music_invalid_file_returns_false(audio: AudioService, tmp_path: Path) -> None:
    bad = tmp_path / "bad.wav"
    bad.write_bytes(b"not-a-wav")
    assert audio.play_music(bad) is False


def _write_wav(path: Path, *, seconds: float = 0.2, rate: int = 8000) -> None:
    import wave

    frames = int(rate * seconds)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x00\x00" * frames)
