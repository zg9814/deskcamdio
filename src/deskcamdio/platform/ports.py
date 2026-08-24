"""Platform ports: the seams between the UI process and hardware/OS."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol


class CameraClientPort(Protocol):
    async def ensure_running(self) -> bool: ...

    def preview_jpeg(self) -> bytes | None: ...

    async def capture(self, quality: str, destination: Path) -> dict[str, Any]: ...

    async def shutdown(self, timeout: float = 2.0) -> None: ...

    @property
    def running(self) -> bool: ...


class SystemControlPort(Protocol):
    def brightness(self) -> float: ...

    def set_brightness(self, value: float) -> None: ...

    def screen_power(self, enabled: bool) -> None: ...

    def request_shutdown(self) -> None: ...

    def battery_or_power_state(self) -> str: ...


class ButtonEventsPort(Protocol):
    def subscribe(self, action: str, callback: Callable[[], None]) -> Callable[[], None]: ...

    def close(self) -> None: ...


def unavailable(name: str) -> Any:
    """Raise a descriptive error for hardware not present on this host."""

    def raiser(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError(f"{name} requires Raspberry Pi hardware")

    return raiser
