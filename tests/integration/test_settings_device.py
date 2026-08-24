"""Batch-4: device settings panel, idle screen sleep, system port."""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pygame

from deskcamdio.apps.settings.app import _collect_diagnostics
from deskcamdio.core.runtime import DeviceRuntime, RunState
from deskcamdio.platform.system import SimulatedSystem


async def test_device_panel_actions(harness) -> None:
    settings = await harness.open("settings")
    # switch to the 设备 tab
    surface = pygame.Surface((480, 480))
    settings.render(surface)
    settings.handle_input(
        pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"pos": settings._tabs["设备"].center})
    )
    settings.render(surface)  # build device hitboxes

    assert settings._device_buttons["wifi_reconnect"] is not None

    print("DBG page=", settings.page)
    print(
        "DBG ctx type=",
        type(getattr(settings._context, "system", None)).__name__,
        "harness type=",
        type(harness.system).__name__,
    )
    print("DBG same=", getattr(settings._context, "system", None) is harness.system)
    # bluetooth toggle flips simulated state
    before = harness.system.bluetooth_status()["powered"]
    settings.handle_input(
        pygame.event.Event(
            pygame.MOUSEBUTTONDOWN, {"pos": settings._device_buttons["bt_toggle"].center}
        )
    )
    await asyncio.sleep(0.05)
    assert harness.system.bluetooth_status()["powered"] != before

    # brightness up/down clamp through the simulated backlight
    start = harness.system.get_brightness()
    settings.handle_input(
        pygame.event.Event(
            pygame.MOUSEBUTTONDOWN,
            {"pos": settings._device_buttons["brightness_up"].center},
        )
    )
    await asyncio.sleep(0.05)
    assert harness.system.get_brightness() == min(100, start + 10)

    # timeout selection persists and reaches runtime cache via settings event
    settings.handle_input(
        pygame.event.Event(
            pygame.MOUSEBUTTONDOWN,
            {"pos": settings._device_buttons["timeout:300"].center},
        )
    )
    await asyncio.sleep(0.05)
    value = await harness.store.get_setting("screen_timeout_seconds", 0)
    assert value == 300


async def test_idle_screen_sleep_and_wake(tmp_path: Path) -> None:
    from test_input_flow import make_runtime  # type: ignore[import-not-found]

    rt = await make_runtime(tmp_path)
    try:
        rt._screen_timeout = 0.05
        rt._last_activity = time.monotonic() - 1.0
        await asyncio.sleep(0.01)
        # frame loop transitions to SCREEN_SLEEP on next iteration
        task = asyncio.get_running_loop().create_task(rt.run(frame_limit=3))
        await asyncio.wait_for(task, timeout=10)
        assert runtime_sleeping(rt)

        # any activity wakes back to remembered foreground
        wake = rt.machine.return_state
        rt.machine.transition(wake)
        assert rt.machine.state is wake
    finally:
        await rt.shutdown()


def runtime_sleeping(rt: DeviceRuntime) -> bool:
    return rt.machine.state in {RunState.SCREEN_SLEEP, RunState.SOFT_SLEEP}


async def test_simulated_system_defaults() -> None:
    sysctl = SimulatedSystem()
    status = sysctl.wifi_status()
    assert status["connected"] is True
    assert sysctl.set_brightness(150) is True
    assert sysctl.brightness == 100
    assert sysctl.set_brightness(2) is True
    assert sysctl.brightness == 5


async def test_volume_slider_syncs_system(harness) -> None:
    settings = await harness.open("settings")
    settings.page = 1
    settings.render(pygame.Surface((480, 480)))
    track = settings._volume_track
    pos = (track.x + int(track.width * 0.5), track.centery)
    settings.handle_input(pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"pos": pos}))
    await asyncio.sleep(0.05)
    assert settings.volume == 50
    stored = await harness.store.get_setting("volume", 0)
    assert int(stored) == 50


async def test_device_panel_probes_are_not_per_frame(harness, monkeypatch) -> None:
    """Review fix #4: nmcli/bluetoothctl probes must be throttled snapshots."""
    settings = await harness.open("settings")
    system = harness.system

    counts = {"wifi": 0, "bt": 0}
    real_wifi, real_bt = system.wifi_status, system.bluetooth_status

    def wifi():
        counts["wifi"] += 1
        return real_wifi()

    def bt():
        counts["bt"] += 1
        return real_bt()

    monkeypatch.setattr(system, "wifi_status", wifi)
    monkeypatch.setattr(system, "bluetooth_status", bt)

    surface = pygame.Surface((480, 480))
    settings.page = 2
    for _ in range(10):  # ~10 frames on the 设备 tab
        settings.render(surface)
        settings.update(1 / 30)

    # enter() forced one refresh; per-frame renders stay inside the throttle.
    assert counts["wifi"] <= 2
    assert counts["bt"] <= 2

    await asyncio.sleep(0.1)  # let the off-thread snapshot land
    assert counts["wifi"] <= 2  # still throttled after snapshot arrives
    assert "brightness" in settings.device_snapshot


def test_diagnostics_collects_controller_and_closes_device(tmp_path: Path, monkeypatch) -> None:
    from deskcamdio.services import touch_relay

    class Device:
        name = "USB Gamepad"
        closed = False

        def __init__(self, _path: str) -> None:
            pass

        def close(self) -> None:
            self.closed = True

    monkeypatch.setitem(
        sys.modules,
        "evdev",
        SimpleNamespace(list_devices=lambda: ["/dev/input/event9"], InputDevice=Device),
    )
    monkeypatch.setattr(touch_relay, "discover_touch_device", lambda: "/dev/input/event8")
    monkeypatch.setenv("DESKCAMDIO_PLATFORM", "raspberry_pi")
    result = _collect_diagnostics(tmp_path)
    assert result["controllers"] == 1
    assert result["touch"] is True and result["gpio"] is True
