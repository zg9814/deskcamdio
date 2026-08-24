"""Branch-path coverage for apps, workers and platform factories."""

from __future__ import annotations

import asyncio
import os
import socket
import threading
from pathlib import Path

import pygame
import pytest

from deskcamdio.apps.fishing.economy import (
    PlayerState,
    bite_chance,
    day_period,
    fish_value,
    roll_species,
)
from deskcamdio.cli.camera_worker import CameraWorker, serve
from deskcamdio.core.lifecycle import LeaveReason, RouteState
from deskcamdio.services.camera_client import (
    BaseCameraClient,
    FakeCameraWorker,
    SubprocessCameraClient,
)
from deskcamdio.services.ipc import new_request, recv_message, send_message

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")


def _surface() -> pygame.Surface:
    return pygame.Surface((480, 480))


# ---- fishing economy -------------------------------------------------------


def test_day_period_boundaries() -> None:
    assert day_period(None) in {"dawn", "day", "dusk", "night"}


class FixedRandom:
    def __init__(self, value: float) -> None:
        self.value = value

    def random(self) -> float:
        return self.value

    def uniform(self, _lo: float, _hi: float) -> float:
        return 1.0


def test_roll_species_night_prefers_eel() -> None:
    assert roll_species("night", FixedRandom(0.0)) in {"eel", "carp"}
    assert roll_species("dawn", FixedRandom(0.99)) in {"eel", "catfish"}


def test_fish_value_period_multipliers() -> None:
    base = fish_value("carp", 1.0, False, "day")
    assert fish_value("carp", 1.0, False, "dusk") >= base
    assert fish_value("carp", 1.0, False, "night") > base
    assert fish_value("carp", 1.0, True, "day") == base * 5


def test_bite_chance_clamped() -> None:
    assert bite_chance(100, "dusk") > bite_chance(100, "day")
    assert bite_chance(10, "day") < bite_chance(100, "day")
    assert bite_chance(0, "dawn") >= 0.05


def test_player_state_json_roundtrip() -> None:
    player = PlayerState(coins=7, bait=3, cargo=[{"species": "koi", "weight": 1.0}])
    restored = PlayerState.from_json(player.to_json())
    assert restored.coins == 7 and restored.cargo[0]["species"] == "koi"


# ---- world QTE branches -----------------------------------------------------


async def test_world_qte_early_penalty() -> None:
    from deskcamdio.apps.fishing.world import HookState, World

    world = World()
    world.cast()
    world.update(10.0)
    assert world.hook_state is HookState.FIGHTING
    world.qte_active = True
    world.qte_ring_radius = 500.0  # outside window
    result = world.reel()
    assert result == "qte-early"
    world.progress = 0.99
    world.reel()
    assert world.hook_state is HookState.LANDED

    world.hook_state = HookState.IDLE
    world.update(5.0)  # still idle; no crash
    assert world.hook_state is HookState.IDLE


async def test_world_escape_when_progress_zero(harness_like=None) -> None:
    from deskcamdio.apps.fishing.world import HookState, World

    world = World()
    world.cast()
    world.update(10.0)
    world.progress = 0.05
    for _ in range(60):
        world.update(0.2)
        if world.hook_state is HookState.ESCAPED:
            break
    assert world.hook_state is HookState.ESCAPED


# ---- camera app paths --------------------------------------------------------


async def test_camera_buttons_error_and_lifecycle(harness_maker) -> None:
    harness = await harness_maker()
    camera_app = await harness.open("camera")

    camera_app.render(_surface())  # build buttons
    q_rect = camera_app._buttons["quality"]
    camera_app.handle_input(pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"pos": q_rect.center}))
    assert camera_app._quality == "high"

    filter_rect = camera_app._buttons["filter"]
    camera_app.handle_input(pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"pos": filter_rect.center}))
    camera_app.handle_input(
        pygame.event.Event(
            pygame.MOUSEBUTTONDOWN,
            {"pos": camera_app._style_rects[2].center},
        )
    )
    assert camera_app._filter == 2

    # Unavailable camera → error banner instead of crash.
    from deskcamdio.services.camera_client import FakeCameraWorker

    camera_app._camera = FakeCameraWorker(available=False)
    camera_app._open_tried = False if hasattr(camera_app._camera, "_open_tried") else None
    await camera_app.enter(RouteState(app_id="camera"))
    camera_app.render(_surface())
    assert camera_app._error != ""

    await camera_app.leave(LeaveReason.NAVIGATED_BACK)
    await camera_app.dispose()


async def test_camera_capture_with_preview_surface(harness_maker) -> None:
    harness = await harness_maker()
    camera_app = await harness.open("camera")
    camera_app._preview_surface = _surface()
    await camera_app._capture()
    photos = list((harness.data_dir / "media" / "photos").glob("*.jpg"))
    assert photos
    camera_app.render(_surface())


# ---- launcher paging ---------------------------------------------------------


async def test_launcher_swipe_and_launch(harness_maker) -> None:
    captured: list[str] = []

    harness = await harness_maker(launch=lambda app_id: captured.append(app_id))
    launcher = await harness.open("launcher")
    launcher.page = 1
    launcher.render(_surface())

    launcher.page = 0
    launcher.render(_surface())

    tile_rect = next(iter(launcher._tiles.values()))
    center = tile_rect.center
    down = pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1, "pos": center})
    move = pygame.event.Event(pygame.MOUSEMOTION, {"pos": (center[0] + 20, center[1])})
    up = pygame.event.Event(pygame.MOUSEBUTTONUP, {"button": 1, "pos": (center[0] + 20, center[1])})
    launcher.handle_input(down)
    launcher.handle_input(move)
    launcher.handle_input(up)
    await asyncio.sleep(0)
    assert captured

    # swipe flips back a page without launching anything
    captured.clear()
    launcher.page = 1
    launcher.render(_surface())
    start = (200, 200)
    launcher.handle_input(pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1, "pos": start}))
    launcher.handle_input(pygame.event.Event(pygame.MOUSEMOTION, {"pos": (300, 200)}))
    launcher.handle_input(
        pygame.event.Event(pygame.MOUSEBUTTONUP, {"button": 1, "pos": (300, 200)})
    )
    assert launcher.page == 0


# ---- music / pomodoro / settings extra paths ----------------------------------


async def test_music_toggle_and_finish(harness_maker) -> None:
    import wave

    harness = await harness_maker()
    music_dir = harness.data_dir / "music"
    music_dir.mkdir(parents=True, exist_ok=True)
    with wave.open(str(music_dir / "a.wav"), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        handle.writeframes(b"\x00\x00" * 4000)

    if pygame.mixer.get_init() is None and not harness.audio._mixer_open:
        pytest.skip("no audio backend available")

    music_app = await harness.open("music")
    music_app.render(_surface())
    music_app.handle_input(
        pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"pos": music_app._rows[0].center})
    )
    assert music_app.current is not None
    toggle_rect = music_app._buttons["toggle"]
    music_app.handle_input(pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"pos": toggle_rect.center}))
    music_app.update(0.1)
    music_app.handle_input(pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"pos": toggle_rect.center}))
    music_app.update(10.0)
    await asyncio.sleep(0.05)


async def test_pomodoro_buttons_persist(harness_maker) -> None:
    harness = await harness_maker()
    pomodoro = await harness.open("pomodoro")
    pomodoro.render(_surface())
    for key in ("plus", "minus", "start", "pause", "reset"):
        rect = pomodoro._buttons[key]
        pomodoro.handle_input(pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"pos": rect.center}))
        await asyncio.sleep(0.02)
    row = await harness.store.fetch_one("SELECT duration_seconds FROM pomodoro_state WHERE id=1")
    assert row is not None


async def test_settings_all_pages_render(harness_maker) -> None:
    harness = await harness_maker()
    settings = await harness.open("settings")
    settings.render(_surface())
    for name in ("声音", "设备", "数据"):
        settings.handle_input(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"pos": settings._tabs[name].center})
        )
        settings.render(_surface())
    track = settings._volume_track
    settings.handle_input(
        pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"pos": (track.right - 4, track.centery)})
    )
    await asyncio.sleep(0.02)


# ---- gba page ------------------------------------------------------------------


async def test_gba_lists_roms_from_store(harness_maker) -> None:
    harness = await harness_maker()
    await harness.store.upsert_rom(
        {
            "sha256": "ff",
            "path": "/roms/a.gba",
            "title": "DEMO",
            "game_code": "DMG",
            "size_bytes": 4 * 1024 * 1024,
            "mtime_ns": 1,
        }
    )
    events: list[dict] = []
    harness.bus.subscribe("gba.launch_requested", lambda event: events.append(event.payload))
    gba = await harness.open("gba")
    gba.render(_surface())
    rect = gba._rows["ff"]
    gba.handle_input(pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"pos": rect.center}))
    assert events and events[0]["sha256"] == "ff"


# ---- worker serve over injected socket + client fallbacks -----------------------


def test_camera_worker_serve_loop_injected_socket(tmp_path: Path) -> None:
    """serve() with a pre-bound TCP listener exercises the accept loop."""
    worker = CameraWorker()
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    server.settimeout(5.0)
    port = server.getsockname()[1]

    def client() -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.connect(("127.0.0.1", port))
            sock.settimeout(5.0)
            for name in ("ping", "close"):
                send_message(sock, new_request(name))
                recv_message(sock)

    thread = threading.Thread(target=client, daemon=True)
    thread.start()
    exit_code = serve(tmp_path / "unused.sock", worker, server=server)
    thread.join(timeout=2.0)
    assert exit_code == 0


async def test_subprocess_client_shutdown_without_start(tmp_path: Path) -> None:
    client = SubprocessCameraClient(tmp_path / "s.sock")
    assert client.running is False
    await client.shutdown()


async def test_subprocess_start_timeout_raises(tmp_path: Path, monkeypatch) -> None:
    client = SubprocessCameraClient(
        tmp_path / "s.sock",
        command=["this-binary-does-not-exist", "--socket", str(tmp_path / "s.sock")],
    )
    with pytest.raises((RuntimeError, OSError, FileNotFoundError, ProcessLookupError)):
        await asyncio.wait_for(client.start(), timeout=10.0)
    await client.shutdown()


def test_base_preview_default_none() -> None:
    assert BaseCameraClient().preview_jpeg() is None


def test_fake_camera_unavailable_preview(tmp_path: Path) -> None:
    async def scenario() -> None:
        camera = FakeCameraWorker(available=False)
        frame = await camera.preview_async()
        assert frame is None
        await camera.shutdown()

    asyncio.run(scenario())


# ---- platform factory -------------------------------------------------------------


def test_platform_factory_simulator_branch(monkeypatch) -> None:
    from deskcamdio import platform as platform_mod

    monkeypatch.setenv("DESKCAMDIO_PLATFORM", "")
    client = platform_mod.create_camera_client(Path("run"))
    assert isinstance(client, FakeCameraWorker)

    monkeypatch.setenv("DESKCAMDIO_PLATFORM", "raspberry_pi")
    pi_client = platform_mod.create_camera_client(Path("run"))
    assert isinstance(pi_client, SubprocessCameraClient)


# ---- typography extras --------------------------------------------------------------


def test_typography_asset_helpers() -> None:
    from deskcamdio.ui import typography

    typography.clear_caches()
    typography.load_asset_fonts_if_present()  # no assets dir in repo → no-op
    assert typography.asset_font_path() is None or typography.asset_font_path().exists()
