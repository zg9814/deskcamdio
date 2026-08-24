"""Gallery ThumbnailCache single-flight dispatch (rc1 review fix #3)."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pygame

from deskcamdio.apps.gallery.app import ThumbnailCache


class RecordingScope:
    """Fake TaskScope: records dispatched worker names, runs them for real."""

    def __init__(self) -> None:
        self.names: list[str] = []

    def run_in_thread(self, fn, *, name=None):  # noqa: ANN001, ANN202
        self.names.append(name or "")
        threading.Thread(target=fn, daemon=True).start()


def _photo(tmp_path: Path) -> Path:
    surface = pygame.Surface((48, 48))
    surface.fill((180, 30, 30))
    photo = tmp_path / "shot.jpg"
    pygame.image.save(surface, str(photo))
    return photo


def _wait_until(predicate, timeout_s: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def test_same_source_dispatches_only_one_decode(tmp_path: Path, monkeypatch) -> None:
    """render() hits get() every frame; slow decodes must not fan out threads."""
    real_load = pygame.image.load
    gate = threading.Event()

    def slow_load(path, *args, **kwargs):  # noqa: ANN001, ANN202
        gate.wait(3.0)  # keep the decode in-flight while frames tick
        return real_load(path, *args, **kwargs)

    monkeypatch.setattr(pygame.image, "load", slow_load)

    scope = RecordingScope()
    cache = ThumbnailCache()
    photo = _photo(tmp_path)

    for _ in range(20):  # ~20 frames against one in-flight decode
        assert cache.get(photo, tmp_path, scope=scope) is None

    assert scope.names == ["gallery-thumb"]  # exactly ONE dispatch, not 20

    gate.set()  # let the decode finish and land in the LRU
    assert _wait_until(lambda: cache.get(photo, tmp_path) is not None)
    assert scope.names.count("gallery-thumb") == 1


def test_memory_hit_skips_dispatch(tmp_path: Path) -> None:
    scope = RecordingScope()
    cache = ThumbnailCache()
    photo = _photo(tmp_path)

    assert cache.get(photo, tmp_path, scope=scope) is None
    assert _wait_until(lambda: cache.get(photo, tmp_path) is not None)

    surface = cache.get(photo, tmp_path, scope=scope)
    assert surface is not None  # served from LRU, no new dispatch
    assert scope.names.count("gallery-thumb") == 1


def test_failed_decode_releases_inflight_slot(tmp_path: Path, monkeypatch) -> None:
    cache = ThumbnailCache()
    photo = _photo(tmp_path)

    def boom(*_args, **_kwargs):
        raise RuntimeError("corrupt image")

    monkeypatch.setattr(pygame.image, "load", boom)
    cache.get(photo, tmp_path, scope=None)  # daemon thread fails fast
    assert _wait_until(lambda: not cache._inflight)

    cache.get(photo, tmp_path, scope=None)  # must be dispatchable again
    assert _wait_until(lambda: not cache._inflight)
