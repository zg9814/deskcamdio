from __future__ import annotations

import json
from pathlib import Path

import pytest

from deskcamdio.core.events import EventBus
from deskcamdio.services.state_store import open_store


@pytest.fixture()
def bus() -> EventBus:
    return EventBus()


@pytest.fixture()
async def store(tmp_path: Path, bus: EventBus):
    store = await open_store(tmp_path / "state.db", bus)
    yield store
    await store.close()


async def test_migrations_idempotent(tmp_path: Path, bus: EventBus) -> None:
    first = await open_store(tmp_path / "state.db", bus)
    rows = await first.fetch_all("SELECT version FROM schema_migrations")
    assert [r[0] for r in rows] == [1]
    tables = {
        r[0] for r in await first.fetch_all("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {
        "settings",
        "memos",
        "pomodoro_state",
        "pomodoro_daily",
        "fishing_state",
        "fishing_collection",
        "gba_roms",
    } <= tables
    await first.close()

    second = await open_store(tmp_path / "state.db", bus)
    assert [r[0] for r in await second.fetch_all("SELECT version FROM schema_migrations")] == [1]
    await second.close()


async def test_settings_roundtrip_publishes_event(store, bus: EventBus) -> None:
    seen: list[str] = []
    bus.subscribe("settings.changed", lambda _e: seen.append("settings.changed"))

    await store.set_setting("volume", 42)
    await store.set_setting("theme", "fish")
    assert await store.get_setting("volume") == 42
    assert await store.get_setting("missing", "dft") == "dft"
    assert seen == ["settings.changed", "settings.changed"]


async def test_memo_crud_events(store, bus: EventBus) -> None:
    events: list[str] = []
    bus.subscribe("memo.changed", lambda _e: events.append("memo.changed"))

    memo_id = await store.add_memo("买鱼粮")
    memos = await store.list_memos()
    assert len(memos) == 1 and memos[0]["body"] == "买鱼粮"

    await store.set_memo_completed(memo_id, True)
    assert (await store.list_memos())[0]["completed"] is True

    await store.delete_memo(memo_id)
    assert await store.list_memos() == []
    assert len(events) == 3


async def test_pomodoro_and_fishing_helpers(store) -> None:
    await store.save_pomodoro(duration=1500, remaining=1499, running=True)
    row = await store.fetch_one("SELECT duration_seconds, running FROM pomodoro_state WHERE id=1")
    assert row == (1500, 1)

    await store.bump_pomodoro_daily("2026-08-23")
    await store.bump_pomodoro_daily("2026-08-23", 2)
    daily = await store.fetch_one(
        "SELECT completed_count FROM pomodoro_daily WHERE day='2026-08-23'"
    )
    assert daily == (3,)

    await store.save_fishing_state(json.dumps({"coins": 10}, ensure_ascii=False))
    state_row = await store.fetch_one("SELECT state_json FROM fishing_state WHERE id=1")
    assert json.loads(str(state_row[0]))["coins"] == 10

    await store.record_catch("carp", "small", False, 123.5)
    await store.record_catch("carp", "small", False, 124.0)
    counts = await store.fetch_one("SELECT count FROM fishing_collection WHERE species='carp'")
    assert counts == (2,)


async def test_rom_upsert_and_touch(store) -> None:
    record = {
        "sha256": "abc",
        "path": "/var/lib/deskcamdio/roms/gba/a.gba",
        "title": "TEST",
        "game_code": "TSTT",
        "size_bytes": 1024,
        "mtime_ns": 7,
    }
    await store.upsert_rom(record)
    await store.upsert_rom({**record, "mtime_ns": 8})
    rows = await store.fetch_all("SELECT sha256, mtime_ns FROM gba_roms")
    assert rows == [("abc", 8)]
    await store.upsert_rom({**record, "sha256": "def", "title": "REPLACED"})
    rows = await store.fetch_all("SELECT sha256, path, title FROM gba_roms")
    assert rows == [("def", record["path"], "REPLACED")]
    await store.touch_rom("def")
    played = await store.fetch_one("SELECT last_played_at FROM gba_roms WHERE sha256='def'")
    assert played is not None and played[0] is not None


async def test_close_flushes_pending_operations(tmp_path: Path, bus: EventBus) -> None:
    store = await open_store(tmp_path / "state.db", bus)
    await store.set_setting("flushed", True)
    await store.close()
    check = await open_store(tmp_path / "state.db", bus)
    assert await check.get_setting("flushed") is True
    await check.close()


async def test_concurrent_submissions_serialize(store) -> None:
    async def writer(index: int) -> None:
        await store.set_setting(f"key{index}", index)

    await __import__("asyncio").gather(*(writer(i) for i in range(20)))
    for i in range(20):
        assert await store.get_setting(f"key{i}") == i
