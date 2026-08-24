"""TouchRelay unit tests: decode, scaling, state machine, discovery."""

from __future__ import annotations

from pathlib import Path

import pygame
import pytest

from deskcamdio.services.touch_relay import (
    ABS_X,
    ABS_Y,
    BTN_TOUCH,
    EV_ABS,
    EV_KEY,
    EVENT_STRUCT,
    AbsAxisRange,
    TouchRelay,
    decode_events,
    discover_touch_device,
)


def pack(etype: int, code: int, value: int) -> bytes:
    return EVENT_STRUCT.pack(0, 0, etype, code, value)


@pytest.fixture(autouse=True)
def _pygame_ready() -> None:
    """Earlier integration tests may have called pygame.quit(); restore."""
    pygame.display.init()
    pygame.font.init()


@pytest.fixture()
def drained_events() -> list[pygame.event.Event]:
    pygame.event.get()  # drain queue from other tests
    return []


def test_decode_events_roundtrip_and_tail_junk() -> None:
    chunk = pack(EV_ABS, ABS_X, 10) + pack(EV_KEY, BTN_TOUCH, 1) + b"\x00" * 5
    records = decode_events(chunk)
    assert records == [(EV_ABS, ABS_X, 10), (EV_KEY, BTN_TOUCH, 1)]


def test_abs_axis_scale_clamps() -> None:
    axis = AbsAxisRange(100, 1100)
    assert axis.scale(100, 480) == 0
    assert axis.scale(600, 480) == 240
    assert axis.scale(99_999, 480) == 479
    degenerate = AbsAxisRange(5, 5)
    assert degenerate.scale(5, 480) == 0


def _relay() -> TouchRelay:
    return TouchRelay(
        "/dev/input/fake",
        (480, 320),
        x_range=AbsAxisRange(0, 2000),
        y_range=AbsAxisRange(0, 2000),
    )


def test_press_motion_release_sequence(drained_events) -> None:
    relay = _relay()
    relay.consume(
        [
            (EV_ABS, ABS_X, 1000),
            (EV_ABS, ABS_Y, 1600),
            (EV_KEY, BTN_TOUCH, 1),
            (EV_ABS, ABS_X, 500),
        ]
    )
    events = pygame.event.get()
    kinds = [e.type for e in events]
    assert kinds[0] == pygame.MOUSEMOTION
    assert kinds.count(pygame.MOUSEBUTTONDOWN) == 1
    down = next(e for e in events if e.type == pygame.MOUSEBUTTONDOWN)
    assert down.pos == (240, 256)
    assert down.button == 1 and down.buttons == (1, 0, 0)
    motion = next(e for e in events if e.type == pygame.MOUSEMOTION and e.buttons == (1, 0, 0))
    assert motion.pos == (120, 256)

    relay.consume([(EV_KEY, BTN_TOUCH, 0)])
    ups = [e for e in pygame.event.get() if e.type == pygame.MOUSEBUTTONUP]
    assert len(ups) == 1 and ups[0].pos == (120, 256)
    assert ups[0].button == 1 and ups[0].buttons == (1, 0, 0)


def test_press_without_coordinates_is_ignored(drained_events) -> None:
    relay = _relay()
    relay.consume([(EV_KEY, BTN_TOUCH, 1)])
    assert pygame.event.get() == []
    assert relay._pressed is False


def _map_sysfs_glob_to(tmp_path: Path, monkeypatch) -> None:
    """Point the module's glob at a fake /sys/class/input tree."""
    import glob as glob_module

    import deskcamdio.services.touch_relay as tr

    real_glob = glob_module.glob

    def fake_glob(pattern: str):
        if "/sys/class/input" in pattern:
            mapped = pattern.replace("/sys/class/input", str(tmp_path))
            return sorted(real_glob(mapped))
        return real_glob(pattern)

    monkeypatch.setattr(tr.glob, "glob", fake_glob)


def test_discover_touch_device_by_name(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("DESKCAMDIO_TOUCH_DEVICE", raising=False)
    touch = tmp_path / "input3"
    touch.mkdir()
    (touch / "name").write_text("wch.cn USB2IIC_CTP_CONTROL\n", encoding="utf-8")
    (touch / "event4").mkdir()
    _map_sysfs_glob_to(tmp_path, monkeypatch)
    assert discover_touch_device() == "/dev/input/event4"


def test_discover_no_match_returns_none(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("DESKCAMDIO_TOUCH_DEVICE", raising=False)
    other = tmp_path / "input1"
    other.mkdir()
    (other / "name").write_text("vc4-hdmi\n", encoding="utf-8")
    (other / "event0").mkdir()
    _map_sysfs_glob_to(tmp_path, monkeypatch)
    assert discover_touch_device() is None


def test_discover_env_override_wins(monkeypatch) -> None:
    monkeypatch.setenv("DESKCAMDIO_TOUCH_DEVICE", "/dev/input/event9")
    assert discover_touch_device() == "/dev/input/event9"


def test_relay_stop_before_open_is_clean(tmp_path: Path) -> None:
    relay = TouchRelay(str(tmp_path / "missing"), (480, 320))
    relay.start()
    relay.stop()
    relay.join(timeout=2.0)
    assert not relay.is_alive()


def test_relay_run_reads_regular_file_and_posts(drained_events, tmp_path: Path) -> None:
    import time as _time

    payload = pack(EV_ABS, ABS_X, 1000) + pack(EV_ABS, ABS_Y, 1000) + pack(EV_KEY, BTN_TOUCH, 1)
    device = tmp_path / "fake.event"
    device.write_bytes(payload)

    relay = TouchRelay(
        str(device),
        (480, 320),
        x_range=AbsAxisRange(0, 2000),
        y_range=AbsAxisRange(0, 2000),
    )
    relay.start()
    deadline = _time.monotonic() + 3.0
    downs = []
    while _time.monotonic() < deadline and not downs:
        downs = [e for e in pygame.event.get() if e.type == pygame.MOUSEBUTTONDOWN]
        _time.sleep(0.02)
    relay.stop()
    relay.join(timeout=2.0)
    assert downs and downs[0].pos == (240, 160)
