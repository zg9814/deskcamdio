"""Phase-D depth tests: app business paths and the navigation lifecycle."""

from __future__ import annotations

import asyncio
import wave
from pathlib import Path

import pygame

from deskcamdio.core.lifecycle import RouteState


async def test_navigation_lifecycle_disposes_business_apps(harness) -> None:
    await harness.manager.enter(RouteState(app_id="standby"))
    await harness.manager.enter(RouteState(app_id="memo"))
    assert harness.manager.active_id == "memo"
    assert harness.manager.is_mounted("standby")

    await harness.manager.enter(RouteState(app_id="standby"))
    assert not harness.manager.is_mounted("memo")
    assert harness.manager.is_mounted("standby")


async def test_memo_toggle_and_delete_roundtrip(harness) -> None:
    memo_app = await harness.open("memo")
    memo_id = await harness.store.add_memo("喂鱼")
    await memo_app._reload()

    await harness.store.set_memo_completed(memo_id, True)
    await memo_app._reload()
    entry = next(m for m in memo_app.memos if m["id"] == memo_id)
    assert entry["completed"] is True

    memo_app.render(pygame.Surface((480, 480)))  # populate row hitboxes
    rect = memo_app._rows[f"delete:{memo_id}"]
    memo_app.handle_input(pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"pos": rect.center}))
    await asyncio.sleep(0.05)
    rows = await harness.store.fetch_all("SELECT id FROM memos")
    assert rows == []


async def test_pomodoro_completion_bumps_daily(harness) -> None:
    pomodoro = await harness.open("pomodoro")
    pomodoro.duration = 300
    pomodoro.remaining = 0.01
    pomodoro.running = True
    pomodoro._last_tick = 0.0
    pomodoro.update(0.02)
    await asyncio.sleep(0.05)
    pomodoro.update(0.02)

    await asyncio.sleep(0.05)
    row = await harness.store.fetch_one("SELECT completed_count FROM pomodoro_daily")
    assert row is not None and int(row[0]) >= 1
    assert pomodoro.today_done >= 1


async def test_settings_theme_switch_persists(harness) -> None:
    settings = await harness.open("settings")
    settings.render(pygame.Surface((480, 480)))
    rect = settings._swatches["graphite"]
    settings.handle_input(pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"pos": rect.center}))
    await asyncio.sleep(0.05)
    stored = await harness.store.get_setting("theme", "")
    assert stored == "graphite"


async def test_music_plays_local_file(harness, tmp_path: Path) -> None:
    music_dir = harness.data_dir / "music"
    music_dir.mkdir(parents=True, exist_ok=True)
    with wave.open(str(music_dir / "demo.wav"), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        handle.writeframes(b"\x00\x00" * int(8000 * 0.3))
    (music_dir / "demo.lrc").write_text(
        "[00:00.00]第一句很长很长的歌词需要自动换行\n[00:01.00]第二句\ninvalid",
        encoding="utf-8",
    )

    music_app = await harness.open("music")
    assert len(music_app.tracks) == 1
    music_app._play(music_app.tracks[0])
    assert music_app.current is not None
    assert len(music_app._lyrics) == 2
    assert "第一句" in music_app._current_lyric()
    assert music_app._load_lyrics(music_dir / "missing.lrc") == []
    music_app.update(0.5)
    music_app.render(pygame.Surface((480, 480)))


async def test_gallery_thumbnails_on_disk(harness) -> None:
    from PIL import Image

    photos_dir = harness.data_dir / "media" / "photos"
    photos_dir.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (320, 240), (90, 140, 200)).save(photos_dir / "IMG-1.jpg", format="JPEG")

    gallery = await harness.open("gallery")
    deadline = asyncio.get_running_loop().time() + 3.0
    thumb = None
    while asyncio.get_running_loop().time() < deadline:
        thumb = gallery.cache.get(gallery.photos[0], harness.data_dir)
        if thumb is not None:
            break
        await asyncio.sleep(0.05)
    assert thumb is not None

    gallery.viewer_index = 0
    gallery.render(pygame.Surface((480, 480)))
    assert list((harness.data_dir / "media" / "thumbnails").glob("*.jpg"))


async def test_fishing_shop_purchase_sell_and_upgrade(harness) -> None:
    fishing = await harness.open("fishing")
    fishing.player.coins = 500
    fishing.bait_left = 0
    fishing._buy_bait()
    assert fishing.bait_left == 5
    assert fishing.player.coins == 480

    fishing.warehouse.append({"name": "鱼", "size": "small", "weight": 1, "value": 60})
    fishing._sell_all()
    assert fishing.warehouse == []
    assert fishing.player.coins == 540

    old_level = fishing.player.rod_level
    fishing._upgrade("rod")
    assert fishing.player.rod_level == old_level + 1


async def test_camera_capture_flow_writes_photo(harness, monkeypatch) -> None:
    camera_app = await harness.open("camera")

    async def apply_filter(self, destination):  # noqa: ANN001
        destination.write_bytes(destination.read_bytes())

    monkeypatch.setattr(type(camera_app), "_apply_filter", apply_filter)
    camera_app._filter = 1
    await camera_app._capture()

    photos = list((harness.data_dir / "media" / "photos").glob("*.jpg"))
    assert photos
    assert camera_app._busy is False
