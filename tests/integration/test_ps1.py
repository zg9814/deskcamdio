"""PS1 library and portable RetroArch lifecycle tests."""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

import pytest

from deskcamdio.services.ps1_library import scan_ps1_directory
from deskcamdio.services.ps1_session import RetroArchSession, ensure_ps1_runtime


def test_scan_hides_cue_track_but_keeps_standalone_bin(tmp_path: Path) -> None:
    track = tmp_path / "Disc Track.bin"
    standalone = tmp_path / "Standalone.bin"
    cue = tmp_path / "Disc.cue"
    track.write_bytes(b"track")
    standalone.write_bytes(b"game")
    cue.write_text('FILE "Disc Track.bin" BINARY\n  TRACK 01 MODE2/2352\n', encoding="utf-8")
    (tmp_path / "ignore.txt").write_text("no", encoding="utf-8")

    assert scan_ps1_directory(tmp_path) == [cue, standalone]


def test_retroarch_session_writes_private_config_and_exits(tmp_path: Path) -> None:
    executable = tmp_path / "retroarch_stub.py"
    executable.write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
    core = tmp_path / "pcsx.so"
    core.write_bytes(b"core")
    content = tmp_path / "game.bin"
    content.write_bytes(b"game")
    exits: list[str] = []
    session = RetroArchSession(
        executable,
        core,
        content,
        tmp_path / "data",
        command_prefix=[sys.executable],
        on_exit=exits.append,
    )
    session.start()
    deadline = time.monotonic() + 3
    while not session.poll() and time.monotonic() < deadline:
        time.sleep(0.02)

    config = (tmp_path / "data" / "retroarch" / "retroarch.cfg").read_text(encoding="utf-8")
    assert 'video_force_aspect = "true"' in config
    assert 'input_player1_b_btn = "0"' in config
    assert 'input_player1_a_btn = "1"' in config
    assert 'input_player1_up_btn = "h0up"' in config
    assert session.process is None
    assert session._log_handle is None
    assert exits == ["self-exit"]


def test_ps1_runtime_validation(tmp_path: Path) -> None:
    retroarch = tmp_path / "retroarch"
    core = tmp_path / "core.so"
    with pytest.raises(FileNotFoundError):
        ensure_ps1_runtime(retroarch, core)
    retroarch.write_bytes(b"binary")
    core.write_bytes(b"core")
    assert ensure_ps1_runtime(retroarch, core) == (retroarch, core)


async def test_runtime_launch_event_enters_and_leaves_external_game(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from deskcamdio.core.runtime import DeviceRuntime, RunState
    from deskcamdio.services import ps1_session as ps1_mod

    executable = tmp_path / "retroarch_stub.py"
    executable.write_text("import time\ntime.sleep(60)\n", encoding="utf-8")
    core = tmp_path / "core.so"
    core.write_bytes(b"core")

    class WinSafeRetroArchSession(ps1_mod.RetroArchSession):
        def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
            kwargs.setdefault("command_prefix", [sys.executable])
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(ps1_mod, "RetroArchSession", WinSafeRetroArchSession)
    monkeypatch.setenv("DESKCAMDIO_RETROARCH_BIN", str(executable))
    monkeypatch.setenv("DESKCAMDIO_PCSX_CORE", str(core))

    runtime = DeviceRuntime(
        data_dir=tmp_path / "data",
        run_dir=tmp_path / "run",
        headless=True,
        fps=240,
        health_interval=3600,
    )
    content = runtime.data_dir / "roms" / "ps1" / "game.bin"
    content.parent.mkdir(parents=True)
    content.write_bytes(b"game")
    await runtime.initialize()
    try:
        runtime.launch_app("launcher")
        await asyncio.sleep(0.05)
        runtime.bus.publish("ps1.launch_requested", path=str(content))
        deadline = asyncio.get_running_loop().time() + 3
        while runtime.machine.state is not RunState.EXTERNAL_GAME:
            assert asyncio.get_running_loop().time() < deadline
            await asyncio.sleep(0.02)
        assert runtime.game_session is not None and runtime.game_session.running
        runtime.game_session.request_stop("test")
        deadline = asyncio.get_running_loop().time() + 3
        while runtime.machine.state is not RunState.LAUNCHER:
            assert asyncio.get_running_loop().time() < deadline
            await asyncio.sleep(0.02)
        assert runtime.game_session is None
    finally:
        if runtime.game_session is not None:
            runtime.game_session.request_stop("teardown")
        await runtime.shutdown()
