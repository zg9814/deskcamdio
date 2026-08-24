"""Batch-2 wiring extras: TTS playback, cancel toggle, corrupt thumbnails."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pygame

from deskcamdio.services.audio import AudioService


async def test_play_tts_streams_without_temp_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from test_input_flow import make_runtime

    rt = await make_runtime(tmp_path)
    try:
        consumed: list[bytes] = []

        async def fake_stream(text, consume):  # noqa: ANN001
            async def gen():
                consumed.append(b"RIFFfake")
                yield b"RIFFfake"

            await consume(gen(), "audio/L16;rate=16000")

        assert rt.voice_service is not None
        rt.voice_service.backend.stream_tts = fake_stream  # type: ignore[method-assign]
        await rt._play_tts("你好")
        assert consumed == [b"RIFFfake"]
        assert not (tmp_path / "data" / "voice_reply.wav").exists()
    finally:
        await rt.shutdown()


async def test_toggle_voice_cancels_when_busy(tmp_path: Path) -> None:
    from test_input_flow import make_runtime

    rt = await make_runtime(tmp_path)
    try:
        assert rt.voice_service is not None
        rt.voice_service.state = "listening"
        rt.toggle_voice()
        assert rt.voice_service.abort is True
        # idle state starts a turn task instead of cancelling
        rt.voice_service.state = "idle"

        async def noop_turn():
            # mirror the real service: a fresh turn clears any stale cancel
            rt.voice_service.abort = False
            return "", None

        rt.voice_service.handle_turn = noop_turn  # type: ignore[method-assign]
        rt.toggle_voice()
        await asyncio.sleep(0.01)
        assert rt.voice_service.abort is False
    finally:
        await rt.shutdown()


async def test_gallery_survives_corrupt_photo(harness) -> None:
    photos = harness.data_dir / "media" / "photos"
    photos.mkdir(parents=True, exist_ok=True)
    (photos / "broken.jpg").write_bytes(b"\x00\x01not-a-jpeg")

    gallery = await harness.open("gallery")
    deadline = asyncio.get_running_loop().time() + 1.5
    while asyncio.get_running_loop().time() < deadline:
        if gallery.cache.get(gallery.photos[0], harness.data_dir) is None:
            break
        await asyncio.sleep(0.05)
    surface = pygame.Surface((480, 480))
    gallery.render(surface)  # must not raise


def test_audio_set_volume_clamps_and_applies(harness) -> None:
    audio: AudioService = harness.audio
    audio.set_volume(150)
    assert audio.volume_percent == 100
    audio.set_volume(-5)
    assert audio.volume_percent == 0
    audio.set_volume(55)
    assert audio.volume_percent == 55


import os  # noqa: E402

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
import pytest  # noqa: E402
