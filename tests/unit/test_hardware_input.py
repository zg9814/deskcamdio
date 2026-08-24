from __future__ import annotations

import sys
from types import SimpleNamespace

from deskcamdio.services import hardware_input as hw


class _Encoder:
    def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
        self.args = args
        self.kwargs = kwargs
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _Button:
    def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
        self.args = args
        self.kwargs = kwargs
        self.closed = False

    def close(self) -> None:
        self.closed = True


def test_pi_hardware_emits_rotary_short_and_long(monkeypatch) -> None:
    monkeypatch.setitem(
        sys.modules, "gpiozero", SimpleNamespace(Button=_Button, RotaryEncoder=_Encoder)
    )
    port = hw.RaspberryPiHardwareInput(17, 27, 22)
    seen: list[tuple[str, int]] = []
    unsubscribe = port.subscribe(lambda name, value: seen.append((name, value)))

    port._encoder.when_rotated_clockwise()
    port._encoder.when_rotated_counter_clockwise()
    port._switch.when_pressed()
    port._switch.when_released()
    port._switch.when_pressed()
    port._switch.when_held()
    port._switch.when_held()  # held only fires once
    port._switch.when_released()

    assert seen == [
        ("volume_delta", 5),
        ("volume_delta", -5),
        ("short_press", 1),
        ("long_press", 1),
    ]
    unsubscribe()
    unsubscribe()
    port.close()
    assert port._encoder.closed and port._switch.closed


def test_hardware_factory_platform_and_failure(monkeypatch) -> None:
    monkeypatch.delenv("DESKCAMDIO_PLATFORM", raising=False)
    assert isinstance(hw.create_hardware_input(), hw.NullHardwareInput)
    assert callable(hw.NullHardwareInput().subscribe(lambda *_: None))
    hw.NullHardwareInput().close()

    monkeypatch.setenv("DESKCAMDIO_PLATFORM", "raspberry_pi")
    monkeypatch.setattr(
        hw, "RaspberryPiHardwareInput", lambda *_args: (_ for _ in ()).throw(OSError())
    )
    assert isinstance(hw.create_hardware_input(), hw.NullHardwareInput)
