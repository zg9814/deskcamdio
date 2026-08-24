"""Stdlib-only evdev → pygame touch relay for the KMSDRM kiosk.

SDL's udev-based input enumeration can silently skip input nodes (observed
with a wch.cn USB2IIC capacitive bridge on Raspberry Pi OS, while raw evdev
delivers events fine). This relay reads the kernel device directly — no
third-party modules — and posts synthetic pygame mouse events, so touch
works regardless of SDL backend quirks. The same mechanism will carry EC11
and gamepad input later.
"""

from __future__ import annotations

import contextlib
import glob
import logging
import os
import stat
import struct
import threading
from typing import Any

import pygame

LOGGER = logging.getLogger(__name__)

# input_event on 64-bit: tv_sec(i64) tv_usec(i64) type(u16) code(u16) value(i32)
EVENT_STRUCT = struct.Struct("qqHHi")
BATCH_EVENTS = 32

EV_SYN = 0x00
EV_KEY = 0x01
EV_ABS = 0x03

ABS_X = 0x00
ABS_Y = 0x01
BTN_TOUCH = 0x14A
EVIOCGRAB = 0x40044590


def set_grab(fd: int, enabled: bool) -> bool:
    import importlib

    try:
        fcntl: Any = importlib.import_module("fcntl")
        fcntl.ioctl(fd, EVIOCGRAB, 1 if enabled else 0)
        return True
    except (ImportError, OSError):
        return False


def decode_events(chunk: bytes) -> list[tuple[int, int, int]]:
    """Decode a byte blob into (type, code, value) triples; drops tail junk."""
    records: list[tuple[int, int, int]] = []
    for offset in range(0, len(chunk) - EVENT_STRUCT.size + 1, EVENT_STRUCT.size):
        _sec, _usec, etype, code, value = EVENT_STRUCT.unpack_from(chunk, offset)
        records.append((etype, code, value))
    return records


class AbsAxisRange:
    """Calibration window of one absolute axis."""

    __slots__ = ("minimum", "maximum")

    def __init__(self, minimum: int, maximum: int) -> None:
        self.minimum = minimum
        self.maximum = maximum

    def scale(self, value: int, span: int) -> int:
        if self.maximum <= self.minimum or span <= 0:
            return 0
        ratio = (value - self.minimum) / (self.maximum - self.minimum)
        return max(0, min(span - 1, int(ratio * span)))


def read_abs_range(fd: int, axis: int) -> AbsAxisRange | None:
    """EVIOCGABS(axis) via raw ioctl → min/max calibration, no third-party io."""
    import importlib

    try:
        fcntl = importlib.import_module("fcntl")  # Linux-only; Any-typed on purpose
    except ImportError:  # pragma: no cover - dev host may be Windows
        return None
    size = 24  # input_absinfo: six packed int32 fields
    request = (2 << 30) | (size << 16) | (ord("E") << 8) | (0x40 + axis)
    buf = bytearray(size)
    try:
        fcntl.ioctl(fd, request, buf, True)
    except OSError:
        return None
    _value, minimum, maximum, *_rest = struct.unpack("6i", bytes(buf))
    return AbsAxisRange(minimum, maximum)


def discover_touch_device() -> str | None:
    """Locate the touchscreen evdev node; DESKCAMDIO_TOUCH_DEVICE overrides."""
    override = os.environ.get("DESKCAMDIO_TOUCH_DEVICE")
    if override:
        return override
    tags = ("touch", "ctp", "ft5", "goodix", "gsl", "gt9")
    for name_path in sorted(glob.glob("/sys/class/input/input*/name")):
        try:
            with open(name_path, encoding="utf-8", errors="replace") as handle:
                name = handle.read().strip().lower()
        except OSError:
            continue
        if not any(tag in name for tag in tags):
            continue
        event_dirs = glob.glob(os.path.join(os.path.dirname(name_path), "event*"))
        if event_dirs:
            return "/dev/input/" + os.path.basename(sorted(event_dirs)[0])
    return None


class TouchRelay(threading.Thread):
    """Reads one evdev node and posts synthetic pygame mouse events.

    Single-touch mapping uses the ABS_X/ABS_Y aggregates every MT panel also
    emits, so protocol details (slots/tracking ids) can be ignored safely.
    """

    def __init__(
        self,
        path: str,
        screen_size: tuple[int, int],
        x_range: AbsAxisRange | None = None,
        y_range: AbsAxisRange | None = None,
    ) -> None:
        super().__init__(daemon=True, name="touch-relay")
        self.path = path
        self.screen_size = screen_size
        self.x_range = x_range
        self.y_range = y_range
        self._stop_event = threading.Event()
        self._raw_x: int | None = None
        self._raw_y: int | None = None
        self._pressed = False
        self._motion_dirty = False
        self.ready = threading.Event()
        self.grabbed = False

    def stop(self) -> None:
        self._stop_event.set()

    # ---- coordinate mapping -------------------------------------------------

    def position(self) -> tuple[int, int] | None:
        if self._raw_x is None or self._raw_y is None:
            return None
        width, height = self.screen_size
        x = (
            self.x_range.scale(self._raw_x, width)
            if self.x_range is not None
            else min(max(self._raw_x, 0), width - 1)
        )
        y = (
            self.y_range.scale(self._raw_y, height)
            if self.y_range is not None
            else min(max(self._raw_y, 0), height - 1)
        )
        return x, y

    # ---- state machine over decoded records ----------------------------------

    def consume(self, records: list[tuple[int, int, int]]) -> None:
        for etype, code, value in records:
            self._apply(etype, code, value)
        if self._pressed and self._motion_dirty:
            pos = self.position()
            if pos is not None:
                self._post(pygame.MOUSEMOTION, pos, (0, 0), (1, 0, 0))
            self._motion_dirty = False

    def _apply(self, etype: int, code: int, value: int) -> None:
        if etype == EV_ABS and code == ABS_X:
            self._raw_x = value
            if self._pressed:
                self._motion_dirty = True
        elif etype == EV_ABS and code == ABS_Y:
            self._raw_y = value
            if self._pressed:
                self._motion_dirty = True
        elif etype == EV_KEY and code == BTN_TOUCH:
            self._apply_button(value)

    def _apply_button(self, value: int) -> None:
        if value == 1 and not self._pressed:
            pos = self.position()
            if pos is not None:
                self._pressed = True
                self._post(pygame.MOUSEMOTION, pos, (0, 0), (0, 0, 0))
                self._post(pygame.MOUSEBUTTONDOWN, pos, None, (1, 0, 0))
                self._motion_dirty = False
        elif value == 0 and self._pressed:
            self._pressed = False
            pos = self.position() or (0, 0)
            self._post(pygame.MOUSEBUTTONUP, pos, None, (1, 0, 0))

    @staticmethod
    def _post(
        event_type: int,
        pos: tuple[int, int],
        rel: tuple[int, int] | None,
        buttons: tuple[int, int, int] | None,
    ) -> None:
        payload: dict[str, object] = {"pos": pos}
        if rel is not None:
            payload["rel"] = rel
        if buttons is not None:
            payload["buttons"] = buttons
        if event_type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP):
            payload["button"] = 1
        with contextlib.suppress(pygame.error):
            pygame.event.post(pygame.event.Event(event_type, payload))

    # ---- thread body -----------------------------------------------------------

    def run(self) -> None:  # noqa: C901
        try:
            fd = os.open(self.path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
        except OSError as exc:
            LOGGER.warning("event=touch_relay_open_failed path=%s err=%s", self.path, exc)
            return
        LOGGER.info("event=touch_relay_started device=%s", self.path)
        try:
            try:
                if stat.S_ISCHR(os.fstat(fd).st_mode) and not set_grab(fd, True):
                    raise OSError("EVIOCGRAB unavailable")
                self.grabbed = stat.S_ISCHR(os.fstat(fd).st_mode)
            except OSError as exc:
                LOGGER.warning("event=touch_relay_grab_failed path=%s err=%s", self.path, exc)
                return
            finally:
                self.ready.set()
            if self.x_range is None:
                self.x_range = read_abs_range(fd, ABS_X)
            if self.y_range is None:
                self.y_range = read_abs_range(fd, ABS_Y)
            while not self._stop_event.is_set():
                try:
                    chunk = os.read(fd, EVENT_STRUCT.size * BATCH_EVENTS)
                except BlockingIOError:
                    if self._stop_event.wait(0.01):
                        break
                    continue
                except OSError:
                    break
                if chunk:
                    self.consume(decode_events(chunk))
        finally:
            if self.grabbed:
                set_grab(fd, False)
            with contextlib.suppress(OSError):
                os.close(fd)
            LOGGER.info("event=touch_relay_stopped device=%s", self.path)
