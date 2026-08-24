"""EC11 hardware input port with thread-safe event delivery."""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Callable
from typing import Any

LOGGER = logging.getLogger(__name__)
HardwareCallback = Callable[[str, int], None]


class HardwareInputPort:
    def subscribe(self, callback: HardwareCallback) -> Callable[[], None]:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError


class NullHardwareInput(HardwareInputPort):
    def subscribe(self, callback: HardwareCallback) -> Callable[[], None]:
        del callback
        return lambda: None

    def close(self) -> None:
        return


class RaspberryPiHardwareInput(HardwareInputPort):
    def __init__(self, pin_a: int, pin_b: int, switch_pin: int) -> None:
        from gpiozero import Button, RotaryEncoder

        self._callbacks: list[HardwareCallback] = []
        self._lock = threading.Lock()
        self._long_fired = False
        self._encoder: Any = RotaryEncoder(pin_a, pin_b, max_steps=0, wrap=True)
        self._switch: Any = Button(
            switch_pin, pull_up=True, bounce_time=0.04, hold_time=1.5, hold_repeat=False
        )
        self._encoder.when_rotated_clockwise = lambda: self._emit("volume_delta", 5)
        self._encoder.when_rotated_counter_clockwise = lambda: self._emit("volume_delta", -5)
        self._switch.when_pressed = self._pressed
        self._switch.when_held = self._held
        self._switch.when_released = self._released

    def _pressed(self) -> None:
        with self._lock:
            self._long_fired = False

    def _held(self) -> None:
        with self._lock:
            if self._long_fired:
                return
            self._long_fired = True
        self._emit("long_press", 1)

    def _released(self) -> None:
        with self._lock:
            long_fired = self._long_fired
            self._long_fired = False
        if not long_fired:
            self._emit("short_press", 1)

    def _emit(self, name: str, value: int) -> None:
        for callback in tuple(self._callbacks):
            callback(name, value)

    def subscribe(self, callback: HardwareCallback) -> Callable[[], None]:
        self._callbacks.append(callback)

        def unsubscribe() -> None:
            if callback in self._callbacks:
                self._callbacks.remove(callback)

        return unsubscribe

    def close(self) -> None:
        self._encoder.close()
        self._switch.close()
        self._callbacks.clear()


def create_hardware_input() -> HardwareInputPort:
    if os.getenv("DESKCAMDIO_PLATFORM") != "raspberry_pi":
        return NullHardwareInput()
    try:
        return RaspberryPiHardwareInput(
            int(os.getenv("DESKCAMDIO_EC11_A", "17")),
            int(os.getenv("DESKCAMDIO_EC11_B", "27")),
            int(os.getenv("DESKCAMDIO_EC11_SW", "22")),
        )
    except Exception:  # noqa: BLE001 - device remains usable without GPIO
        LOGGER.exception("event=ec11_unavailable")
        return NullHardwareInput()
