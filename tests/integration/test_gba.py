"""ROM library + GameSession lifecycle tests (hardware-independent)."""

from __future__ import annotations

import sys
import textwrap
import time
from pathlib import Path

import pytest

from deskcamdio.core.events import EventBus
from deskcamdio.services.game_session import (
    COMBO_HOLD_SECONDS,
    ControllerMonitor,
    GameSession,
    ensure_mgba,
)
from deskcamdio.services.rom_library import (
    RomError,
    generate_cover,
    index_directory,
    parse_header,
    safe_slug,
    validate_file,
)


def _seal_checksum(data: bytearray) -> None:
    """Nintendo complement checksum over 0xA0..0xBC (spec formula)."""
    header_sum = sum(data[0xA0:0xBD])
    data[0xBD] = (-(header_sum + 0x19)) & 0xFF


def make_gba(path: Path, title: str = "TESTGAME", code: str = "ABCD", corrupt: bool = False):
    data = bytearray(1024)
    raw_title = title[:12].ljust(12).encode("ascii")
    data[0xA0:0xAC] = raw_title
    data[0xAC:0xB0] = code.ljust(4).encode("ascii")
    data[0xB0:0xB2] = b"01"
    data[0xB2] = 0x96
    _seal_checksum(data)
    if corrupt:
        data[0xB2] = 0x00
        _seal_checksum(data)  # keep checksum self-consistent; fixed byte still wrong
    path.write_bytes(data)
    return path


def test_parse_header_valid() -> None:
    data = bytearray(2048)
    raw_title = b"POKEMON RUBY"
    data[0xA0:0xAC] = raw_title
    data[0xAC:0xB0] = b"AXVE"
    data[0xB2] = 0x96
    _seal_checksum(data)
    header = parse_header(bytes(data))
    assert header.title == "POKEMON RUBY"
    assert header.game_code == "AXVE"
    assert header.fixed_ok and header.checksum_ok


def test_validate_rejects_wrong_size(tmp_path: Path) -> None:
    tiny = tmp_path / "tiny.gba"
    tiny.write_bytes(b"\x00" * 512)
    with pytest.raises(RomError, match="size"):
        validate_file(tiny)

    huge = tmp_path / "huge.gba"
    huge.write_bytes(b"\x00" * (64 * 1024 * 1024 + 1))
    with pytest.raises(RomError, match="size"):
        validate_file(huge)


def test_validate_rejects_corrupt_fixed_byte(tmp_path: Path) -> None:
    rom = make_gba(tmp_path / "bad.gba", corrupt=True)
    with pytest.raises(RomError, match="fixed byte"):
        validate_file(rom)


def test_validate_accepts_good_rom(tmp_path: Path) -> None:
    rom = make_gba(tmp_path / "good.gba")
    header = validate_file(rom)
    assert header.title == "TESTGAME"
    assert header.checksum_ok


def test_safe_slug_strips_hostile_names() -> None:
    assert safe_slug("../../etc/passwd") == ".._.._etc_passwd"
    assert safe_slug("") == "rom"


def test_index_directory_dedupes_and_rejects(tmp_path: Path) -> None:
    store = _FakeStore()
    make_gba(tmp_path / "Good.gba", title="GOODGAME")
    make_gba(tmp_path / "Bad.gba", corrupt=True)

    async def scenario() -> tuple[int, int]:
        first = await index_directory(tmp_path, store)
        second = await index_directory(tmp_path, store)
        return first, second

    import asyncio

    first, second = asyncio.run(scenario())
    # Re-index the same file: hash dedupe keeps one entry per unique ROM.
    records = [r for r in store.records.values() if r["title"] == "Good"]
    assert first >= 1 and second == 0
    assert len(records) == 1


class _FakeStore:
    def __init__(self) -> None:
        self.records: dict[str, dict] = {}

    async def fetch_all(self, _sql: str) -> list[tuple]:
        return [
            (record["path"], sha, record["size_bytes"], record["mtime_ns"])
            for sha, record in self.records.items()
        ]

    async def upsert_rom(self, record: dict) -> None:
        for digest, existing in list(self.records.items()):
            if existing["path"] == record["path"] and digest != record["sha256"]:
                self.records.pop(digest)
        self.records[record["sha256"]] = record


def test_index_replaces_stale_record_for_same_path(tmp_path: Path) -> None:
    import asyncio
    import os

    store = _FakeStore()
    path = make_gba(tmp_path / "replace.gba", title="OLDGAME")
    assert asyncio.run(index_directory(tmp_path, store)) == 1
    old_digest = next(iter(store.records))

    make_gba(path, title="NEWGAME")
    os.utime(path, ns=(2_000_000, 2_000_000))
    assert asyncio.run(index_directory(tmp_path, store)) == 1
    assert len(store.records) == 1
    assert old_digest not in store.records
    assert next(iter(store.records.values()))["title"] == "replace"


def test_generate_cover_is_local_png(tmp_path: Path) -> None:
    cover = generate_cover(tmp_path, "abcd1234" * 4, "MY GAME TITLE LONGER")
    assert cover.exists() and cover.suffix == ".png"
    again = generate_cover(tmp_path, "abcd1234" * 4, "MY GAME TITLE LONGER")
    assert again == cover  # cached on disk


# ---- review fix #6: single-pass hashing + unchanged-file skip -----------------


def test_sha256_file_matches_full_read(tmp_path: Path) -> None:
    import hashlib

    from deskcamdio.services.rom_library import sha256_file

    rom = make_gba(tmp_path / "s.gba")
    rom.write_bytes(rom.read_bytes() + b"\x00" * (3 * 1024 * 1024))  # >1 chunk
    assert sha256_file(rom) == hashlib.sha256(rom.read_bytes()).hexdigest()


def test_index_skips_unchanged_without_hashing(tmp_path: Path, monkeypatch) -> None:
    import asyncio
    import os

    from deskcamdio.services import rom_library as rl

    store = _FakeStore()
    make_gba(tmp_path / "Good.gba", title="GOODGAME")

    async def scenario() -> None:
        await rl.index_directory(tmp_path, store)

    asyncio.run(scenario())

    calls = {"n": 0}
    real = rl.sha256_file

    def counting(path):  # noqa: ANN001, ANN202
        calls["n"] += 1
        return real(path)

    monkeypatch.setattr(rl, "sha256_file", counting)

    assert asyncio.run(rl.index_directory(tmp_path, store)) == 0
    assert calls["n"] == 0  # fingerprint hit → zero content reads

    os.utime(tmp_path / "Good.gba", ns=(1_000_000, 1_000_000))  # mtime bump only
    assert asyncio.run(rl.index_directory(tmp_path, store)) == 0
    assert calls["n"] == 1  # changed file re-hashed exactly once
    assert len(store.records) == 1  # digest dedupe still holds


# ---- GameSession lifecycle ---------------------------------------------------


@pytest.fixture()
def stub_mgba(tmp_path: Path) -> Path:
    """Stub 'mgba': a Python script; tests prepend sys.executable as prefix."""
    script = tmp_path / "mgba_stub.py"
    script.write_text(
        textwrap.dedent(
            """
            import sys, time, signal
            sav_dir = next(
                (a.split("=", 1)[1] for a in sys.argv if a.startswith("general.savegamePath=")),
                ".",
            )
            open(f"{sav_dir}/game.sav", "wb").write(b"SAVEDATA")
            open(f"{sav_dir}/argv.txt", "w", encoding="utf-8").write("\\n".join(sys.argv))
            signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
            while True:
                time.sleep(60)
            """
        ).strip(),
        encoding="utf-8",
    )
    return script


def make_session(stub: Path, tmp_path: Path, rom: Path, **kwargs):
    from deskcamdio.services.game_session import GameSession

    return GameSession(
        stub,
        rom,
        tmp_path / "saves",
        command_prefix=[sys.executable],
        **kwargs,
    )


def test_game_session_full_lifecycle(tmp_path: Path, stub_mgba: Path) -> None:
    rom = make_gba(tmp_path / "zelda.gba", title="ZELDA")
    exits: list[str] = []
    session = make_session(stub_mgba, tmp_path, rom, on_exit=exits.append)
    session.start()
    deadline = __import__("time").monotonic() + 3.0
    while session.running and __import__("time").monotonic() < deadline:
        __import__("time").sleep(0.05)
    session.request_stop("test")
    sav_dir = next((tmp_path / "saves").iterdir())
    assert (sav_dir / "game.sav").exists()
    argv = (sav_dir / "argv.txt").read_text(encoding="utf-8")
    assert "lockAspectRatio=1" in argv
    assert "lockIntegerScaling=1" in argv
    assert "-f" in argv.splitlines()
    assert exits and exits[-1] == "test"


def test_ensure_mgba_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        ensure_mgba(tmp_path / "nope" / "mgba")


def test_controller_monitor_noop_without_evdev() -> None:
    rom = Path("dummy.gba")
    session = GameSession(Path("mgba"), rom, Path("saves"))
    monitor = ControllerMonitor(session, devices=None)
    try:
        import evdev  # noqa: F401

        has_evdev = True
    except ImportError:
        has_evdev = False
    monitor.start()  # must not raise either way
    monitor.stop()
    del has_evdev


def test_double_start_guarded(stub_mgba: Path, tmp_path: Path) -> None:
    rom = make_gba(tmp_path / "g.gba")
    session = make_session(stub_mgba, tmp_path, rom)
    session.start()
    with pytest.raises(RuntimeError, match="already running"):
        session.start()
    session.request_stop("cleanup")


def test_event_bus_importable_for_launch_events() -> None:
    bus = EventBus()
    seen: list[str] = []
    bus.subscribe("gba.launch_requested", lambda e: seen.append(e.topic))
    bus.publish("gba.launch_requested", sha256="x")
    assert seen == ["gba.launch_requested"]


# ---- review fix #7: deterministic coverage for session/monitor edges ---------


def test_session_helpers_safe_before_start(tmp_path: Path) -> None:
    rom = make_gba(tmp_path / "n.gba")
    session = GameSession(Path("mgba"), rom, tmp_path / "saves")
    assert session.running is False
    session.request_stop("idle")  # no-op without a child process
    assert session.exit_reason == ""
    assert session.poll() is False


def test_poll_detects_self_exit(tmp_path: Path) -> None:
    exits: list[str] = []
    rom = make_gba(tmp_path / "q.gba")
    quick = tmp_path / "quick_stub.py"
    quick.write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
    session = GameSession(
        quick,
        rom,
        tmp_path / "saves",
        command_prefix=[sys.executable],
        on_exit=exits.append,
    )
    session.start()
    fired = False
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        if session.poll():
            fired = True
            break
        time.sleep(0.02)
    assert fired
    assert session.exit_reason == "self-exit"
    assert exits[-1] == "self-exit"
    assert session.process is None and session.running is False


def test_shoulder_combo_requires_full_hold(tmp_path: Path) -> None:
    rom = make_gba(tmp_path / "c.gba")
    session = GameSession(Path("mgba"), rom, tmp_path / "saves")
    monitor = ControllerMonitor(session, devices=None)
    held: set[str] = set()

    monitor._update_combo(held, "L1", 1)
    monitor._update_combo(held, "R1", 1)
    monitor._update_combo(held, "L2", 1)
    assert not monitor.stop_flag.is_set()  # 3 of 4 never fires

    monitor._update_combo(held, "R2", 1)
    assert monitor.held_since is not None
    assert not monitor.stop_flag.is_set()  # combo complete but held < threshold

    # Simulate the combo staying held past COMBO_HOLD_SECONDS.
    monitor.held_since -= COMBO_HOLD_SECONDS + 0.5
    monitor._check_combo_hold(held)
    assert monitor.stop_flag.is_set()  # exit requested

    # Releasing any button resets the hold timer.
    monitor.stop_flag.clear()
    monitor._update_combo(held, "L2", 0)
    assert held == {"L1", "R1", "R2"}
    assert monitor.held_since is None
    monitor._update_combo(held, "L2", 1)
    assert monitor.held_since is not None
    assert not monitor.stop_flag.is_set()  # fresh hold restarts the window


def test_controller_monitor_decodes_xinput_keys_and_analog_triggers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeCodes:
        EV_KEY = 1
        EV_ABS = 3
        bytype = {
            EV_KEY: {310: "BTN_TL", 311: "BTN_TR"},
            EV_ABS: {2: "ABS_Z", 5: "ABS_RZ"},
        }

    class FakeEvdev:
        ecodes = FakeCodes

    class Event:
        def __init__(self, event_type: int, code: int, value: int) -> None:
            self.type = event_type
            self.code = code
            self.value = value

    class AbsInfo:
        min = 0
        max = 255

    class Device:
        @staticmethod
        def absinfo(_code: int) -> AbsInfo:
            return AbsInfo()

    monkeypatch.setitem(sys.modules, "evdev", FakeEvdev())
    rom = make_gba(tmp_path / "controller.gba")
    monitor = ControllerMonitor(GameSession(Path("mgba"), rom, tmp_path / "saves"))

    assert monitor._control_of(Event(1, 310, 1)) == ("L1", 1)
    assert monitor._control_of(Event(1, 311, 0)) == ("R1", 0)
    assert monitor._control_of(Event(3, 2, 80), Device()) == ("L2", 0)
    assert monitor._control_of(Event(3, 2, 200), Device()) == ("L2", 1)
    assert monitor._control_of(Event(3, 5, 200), Device()) == ("R2", 1)
    assert monitor._control_of(Event(3, 0, 200), Device()) is None


def test_game_session_writes_private_controller_bindings(tmp_path: Path, stub_mgba: Path) -> None:
    rom = make_gba(tmp_path / "mapped.gba")
    session = make_session(stub_mgba, tmp_path, rom)
    session.start()
    try:
        config = session.saves_dir / ".config" / "mgba" / "config.ini"
        text = config.read_text(encoding="utf-8")
        assert "[gba.input.SDLB]" in text
        assert "keyA=1" in text
        assert "keyStart=7" in text
    finally:
        session.request_stop("cleanup")
