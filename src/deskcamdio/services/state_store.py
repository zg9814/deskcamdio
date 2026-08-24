"""Single-owner SQLite access.

All reads and writes go through one dedicated worker thread that owns the
only connection to ``state.db`` (DEVELOPMENT_GUIDE §6). Callers submit
operations from the event loop and await thread-safe futures; mutating
operations publish change events afterwards.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import queue
import sqlite3
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from deskcamdio.core.events import EventBus

LOGGER = logging.getLogger(__name__)

_PRAGMAS = (
    "PRAGMA journal_mode = WAL",
    "PRAGMA foreign_keys = ON",
    "PRAGMA busy_timeout = 2000",
    "PRAGMA synchronous = NORMAL",
)

_MIGRATIONS: list[tuple[int, str]] = [
    (
        1,
        """
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS memos (
            id INTEGER PRIMARY KEY,
            body TEXT NOT NULL,
            completed INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS pomodoro_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            duration_seconds INTEGER NOT NULL,
            remaining_seconds INTEGER NOT NULL,
            running INTEGER NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS pomodoro_daily (
            day TEXT PRIMARY KEY,
            completed_count INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS fishing_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            state_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS fishing_collection (
            species TEXT NOT NULL,
            size TEXT NOT NULL,
            rare INTEGER NOT NULL,
            first_caught_at REAL NOT NULL,
            count INTEGER NOT NULL,
            PRIMARY KEY (species, size, rare)
        );

        CREATE TABLE IF NOT EXISTS gba_roms (
            sha256 TEXT PRIMARY KEY,
            path TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL,
            game_code TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            mtime_ns INTEGER NOT NULL,
            last_played_at TEXT
        );
        """,
    )
]

_STOP = object()


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())


class StateStore:
    """Async facade over one SQLite worker thread."""

    def __init__(self, db_path: Path, bus: EventBus) -> None:
        self.db_path = db_path
        self.bus = bus
        self._queue: queue.Queue[Any] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self.started = threading.Event()

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._thread = threading.Thread(target=self._worker, name="state-store", daemon=True)
        self._thread.start()
        await self._submit(self._initialise)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=2.0)
        for pragma in _PRAGMAS:
            conn.execute(pragma)
        return conn

    def _worker(self) -> None:
        conn = self._connect()
        try:
            while True:
                item = self._queue.get()
                if item is _STOP:
                    break
                operation, future = item
                try:
                    result = operation(conn)
                    if not future.cancelled():
                        future.set_result(result)
                except BaseException as exc:  # noqa: BLE001 - forwarded to caller
                    if not future.cancelled():
                        future.set_exception(exc)
        finally:
            conn.commit()
            conn.close()

    def _initialise(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        applied = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
        for version, script in _MIGRATIONS:
            if version in applied:
                continue
            with conn:
                conn.executescript(script)
                conn.execute(
                    "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                    (version, _now()),
                )

    async def _submit(
        self, operation: Callable[[sqlite3.Connection], Any], *, topic: str | None = None
    ) -> Any:
        assert self._loop is not None, "start() first"
        future: concurrent.futures.Future[Any] = concurrent.futures.Future()

        def wrapped(_conn: sqlite3.Connection) -> Any:
            result = operation(_conn)
            if topic:
                self.bus.publish(topic)
            return result

        self._queue.put((wrapped, future))
        return await asyncio.wrap_future(future)

    async def close(self) -> None:
        if self._thread is None:
            return
        self._queue.put(_STOP)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._thread.join, 5.0)
        self._thread = None

    # ---- generic helpers -------------------------------------------------

    async def fetch_one(self, sql: str, params: tuple = ()) -> tuple | None:
        return await self._submit(lambda conn: conn.execute(sql, params).fetchone())

    async def fetch_all(self, sql: str, params: tuple = ()) -> list[tuple]:
        return await self._submit(lambda conn: conn.execute(sql, params).fetchall())

    async def execute(self, sql: str, params: tuple = (), *, topic: str | None = None) -> None:
        def operation(conn: sqlite3.Connection) -> None:
            with conn:
                conn.execute(sql, params)

        await self._submit(operation, topic=topic)

    # ---- typed helpers ---------------------------------------------------

    async def get_setting(self, key: str, default: Any = None) -> Any:
        row = await self.fetch_one("SELECT value_json FROM settings WHERE key = ?", (key,))
        if row is None:
            return default
        return json.loads(str(row[0]))

    async def set_setting(self, key: str, value: Any) -> None:
        payload = json.dumps(value, ensure_ascii=False)

        def operation(conn: sqlite3.Connection) -> None:
            with conn:
                conn.execute(
                    "INSERT INTO settings (key, value_json, updated_at) VALUES (?, ?, ?)"
                    " ON CONFLICT(key) DO UPDATE SET"
                    " value_json = excluded.value_json, updated_at = excluded.updated_at",
                    (key, payload, _now()),
                )

        await self._submit(operation)
        self.bus.publish("settings.changed", key=key, value=value)

    async def add_memo(self, body: str) -> int:
        row = await self._submit(lambda conn: self._add_memo(conn, body), topic="memo.changed")
        return int(row)

    @staticmethod
    def _add_memo(conn: sqlite3.Connection, body: str) -> int:
        with conn:
            cursor = conn.execute(
                "INSERT INTO memos (body, completed, created_at, updated_at) VALUES (?, 0, ?, ?)",
                (body, _now(), _now()),
            )
            return int(cursor.lastrowid or 0)

    async def set_memo_completed(self, memo_id: int, completed: bool) -> None:
        await self.execute(
            "UPDATE memos SET completed = ?, updated_at = ? WHERE id = ?",
            (int(completed), _now(), memo_id),
            topic="memo.changed",
        )

    async def delete_memo(self, memo_id: int) -> None:
        await self.execute("DELETE FROM memos WHERE id = ?", (memo_id,), topic="memo.changed")

    async def list_memos(self) -> list[dict[str, Any]]:
        rows = await self.fetch_all(
            "SELECT id, body, completed, created_at FROM memos ORDER BY id DESC"
        )
        return [
            {"id": r[0], "body": r[1], "completed": bool(r[2]), "created_at": r[3]} for r in rows
        ]

    async def save_pomodoro(self, duration: int, remaining: int, running: bool) -> None:
        await self.execute(
            "INSERT INTO pomodoro_state (id, duration_seconds, remaining_seconds, running,"
            " updated_at) VALUES (1, ?, ?, ?, ?)"
            " ON CONFLICT(id) DO UPDATE SET duration_seconds = excluded.duration_seconds,"
            " remaining_seconds = excluded.remaining_seconds, running = excluded.running,"
            " updated_at = excluded.updated_at",
            (duration, remaining, int(running), _now()),
            topic="pomodoro.changed",
        )

    async def bump_pomodoro_daily(self, day: str, amount: int = 1) -> None:
        await self.execute(
            "INSERT INTO pomodoro_daily (day, completed_count) VALUES (?, ?)"
            " ON CONFLICT(day) DO UPDATE SET completed_count = completed_count + ?",
            (day, amount, amount),
            topic="pomodoro.changed",
        )

    async def save_fishing_state(self, state_json: str) -> None:
        await self.execute(
            "INSERT INTO fishing_state (id, state_json, updated_at) VALUES (1, ?, ?)"
            " ON CONFLICT(id) DO UPDATE SET state_json = excluded.state_json,"
            " updated_at = excluded.updated_at",
            (state_json, _now()),
            topic="fishing.changed",
        )

    async def record_catch(self, species: str, size: str, rare: bool, caught_at: float) -> None:
        await self.execute(
            "INSERT INTO fishing_collection (species, size, rare, first_caught_at, count)"
            " VALUES (?, ?, ?, ?, 1)"
            " ON CONFLICT(species, size, rare) DO UPDATE SET count = count + 1",
            (species, size, int(rare), caught_at),
            topic="fishing.changed",
        )

    async def upsert_rom(self, record: dict[str, Any]) -> None:
        await self.execute(
            "INSERT INTO gba_roms (sha256, path, title, game_code, size_bytes, mtime_ns,"
            " last_played_at) VALUES (?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(sha256) DO UPDATE SET path = excluded.path,"
            " mtime_ns = excluded.mtime_ns",
            (
                record["sha256"],
                record["path"],
                record["title"],
                record["game_code"],
                record["size_bytes"],
                record["mtime_ns"],
                record.get("last_played_at"),
            ),
            topic="gba.changed",
        )

    async def touch_rom(self, sha256: str) -> None:
        await self.execute(
            "UPDATE gba_roms SET last_played_at = ? WHERE sha256 = ?",
            (_now(), sha256),
            topic="gba.changed",
        )


async def open_store(db_path: Path, bus: EventBus) -> StateStore:
    store = StateStore(db_path, bus)
    await store.start()
    return store
