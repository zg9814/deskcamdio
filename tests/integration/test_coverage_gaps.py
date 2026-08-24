from __future__ import annotations

import asyncio
from pathlib import Path

import pygame

from deskcamdio.cli.selftest import main as selftest_main
from deskcamdio.services.voice import VoiceService


def test_selftest_returns_1_when_display_fails(monkeypatch) -> None:
    def boom() -> None:
        raise pygame.error("no display")

    monkeypatch.setattr(pygame.display, "init", boom)
    assert selftest_main() == 1


def test_record_pcm_without_arecord(monkeypatch, tmp_path: Path) -> None:
    import shutil as _shutil

    monkeypatch.setattr(_shutil, "which", lambda _name: None)
    service = VoiceService(None, None, data_dir=tmp_path)  # type: ignore[arg-type]
    pcm, reason = asyncio.run(service.record_pcm())
    assert pcm == b""
    assert reason in {"", "cancelled"}
