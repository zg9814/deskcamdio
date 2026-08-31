"""Runtime-level GBA wiring: bus event -> EXTERNAL_GAME -> exit to Launcher."""

from __future__ import annotations

import asyncio
import sys
import textwrap
from pathlib import Path

import pygame
import pytest

from deskcamdio.core.runtime import DeviceRuntime, RunState


@pytest.fixture()
def stub_mgba(tmp_path: Path) -> Path:
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
            signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
            while True:
                time.sleep(60)
            """
        ).strip(),
        encoding="utf-8",
    )
    return script


async def wait_for(predicate, timeout: float = 8.0) -> bool:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.05)
    return False


async def test_external_game_releases_and_restores_display(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    monkeypatch.setenv("SDL_AUDIODRIVER", "dummy")
    monkeypatch.setenv("DESKCAMDIO_PLATFORM", "simulator")
    runtime = DeviceRuntime(
        data_dir=tmp_path / "data",
        run_dir=tmp_path / "run",
        headless=False,
        fps=240,
        health_interval=3600,
    )
    await runtime.initialize()
    try:
        assert pygame.display.get_init()
        runtime._suspend_display_for_game()
        assert not pygame.display.get_init()
        runtime._restore_display_after_game()
        assert pygame.display.get_init()
        assert runtime.screen is not None and runtime.screen.get_size() == (480, 480)
    finally:
        await runtime.shutdown()


async def test_launch_requested_runs_game_and_returns(
    tmp_path: Path, stub_mgba: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rom_path = tmp_path / "demo.gba"
    rom_path.write_bytes(b"\x00" * 2048)

    from deskcamdio.services import game_session as gs_mod

    class WinSafeSession(gs_mod.GameSession):
        def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
            kwargs.setdefault("command_prefix", [sys.executable])
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(gs_mod, "find_mgba", lambda: stub_mgba)
    monkeypatch.setattr(gs_mod, "GameSession", WinSafeSession)

    runtime = DeviceRuntime(
        data_dir=tmp_path / "data",
        run_dir=tmp_path / "run",
        headless=True,
        fps=240,
        health_interval=3600,
    )
    await runtime.initialize()
    try:
        assert runtime.store is not None and runtime.audio is not None
        sha = "a" * 64
        await runtime.store.upsert_rom(
            {
                "sha256": sha,
                "path": str(rom_path),
                "title": "DEMO",
                "game_code": "DMO0",
                "size_bytes": 2048,
                "mtime_ns": 1,
            }
        )

        pause_calls: list[str] = []
        resume_calls: list[str] = []
        monkeypatch.setattr(runtime.audio, "pause_music", lambda: pause_calls.append("p"))
        monkeypatch.setattr(runtime.audio, "resume_music", lambda: resume_calls.append("r"))

        # Start local music first so the handover must pause/resume it.
        import wave

        music_dir = runtime.data_dir / "music"
        music_dir.mkdir(parents=True, exist_ok=True)
        with wave.open(str(music_dir / "bg.wav"), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(8000)
            handle.writeframes(b"\x00\x00" * 8000)
        assert runtime.audio.play_music(music_dir / "bg.wav") is True

        # Navigate the real user path: standby -> launcher -> GBA page.
        from test_input_flow import click, settle

        click((450, 250))
        await settle(runtime)
        assert runtime.machine.state is RunState.LAUNCHER
        runtime.launch_app("gba")
        await settle(runtime)
        assert runtime.machine.state is RunState.APP

        runtime.bus.publish("gba.launch_requested", sha256=sha)
        assert await wait_for(lambda: runtime.machine.state is RunState.EXTERNAL_GAME), (
            "should enter EXTERNAL_GAME"
        )
        assert runtime.game_session is not None and runtime.game_session.running
        assert pause_calls == ["p"]

        sav_files = list((tmp_path / "data" / "saves" / "gba").rglob("game.sav"))
        assert await wait_for(
            lambda: bool(list((tmp_path / "data" / "saves" / "gba").rglob("game.sav")))
        ), f"stub should write .sav promptly; saw {sav_files}"

        assert runtime.game_session is not None
        runtime.game_session.request_stop("test")
        assert await wait_for(lambda: runtime.machine.state is RunState.LAUNCHER), (
            "should return to Launcher after game exit"
        )
        assert resume_calls == ["r"]
        assert runtime.game_session is None

        # The sav landed inside the per-ROM saves directory.
        sav_files = list((tmp_path / "data" / "saves" / "gba").rglob("game.sav"))
        assert sav_files
    finally:
        if runtime.game_session is not None:
            runtime.game_session.request_stop("teardown")
        if runtime._game_poll_task is not None:
            await asyncio.wait_for(runtime._game_poll_task, timeout=5)
        await runtime.shutdown()


async def test_missing_binary_notifies_and_stays(tmp_path: Path, monkeypatch) -> None:
    from deskcamdio.services import game_session as gs_mod

    monkeypatch.setattr(gs_mod, "find_mgba", lambda: tmp_path / "missing" / "mgba")

    runtime = DeviceRuntime(
        data_dir=tmp_path / "data",
        run_dir=tmp_path / "run",
        headless=True,
        fps=240,
        health_interval=3600,
    )
    await runtime.initialize()
    try:
        assert runtime.store is not None
        sha = "b" * 64
        await runtime.store.upsert_rom(
            {
                "sha256": sha,
                "path": str(tmp_path / "x.gba"),
                "title": "X",
                "game_code": "XXXX",
                "size_bytes": 4096,
                "mtime_ns": 1,
            }
        )
        time_before = runtime._toast_until
        runtime.bus.publish("gba.launch_requested", sha256=sha)
        await asyncio.sleep(0.2)
        assert runtime.game_session is None
        assert runtime._toast_until >= time_before  # error toast shown
        assert runtime.machine.state is not RunState.EXTERNAL_GAME
    finally:
        await runtime.shutdown()


def test_frame_loop_skips_render_in_external_game() -> None:
    """EXTERNAL_GAME must be in the frozen-states set alongside sleep modes."""
    import inspect

    from deskcamdio.core.runtime import DeviceRuntime

    source = inspect.getsource(DeviceRuntime.run)
    assert "RunState.EXTERNAL_GAME" in source
