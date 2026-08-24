"""App lifecycle contract for v1.0 plugins.

Every application implements :class:`App`. The runtime guarantees that at
most one business app is mounted at a time and that ``leave``/``dispose``
run before another app enters, so apps can rely on strict ownership of the
resources they create.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Protocol

import pygame


class LeaveReason(Enum):
    """Why an app is leaving the foreground."""

    NAVIGATED_BACK = auto()
    SUPERSEDED = auto()
    FAULT = auto()
    TIMEOUT = auto()
    SHUTDOWN = auto()


@dataclass(frozen=True)
class RouteState:
    """Immutable navigation target handed to ``App.enter``."""

    app_id: str
    args: Mapping[str, str] = field(default_factory=dict)


AppContext = Any  # runtime-provided bundle (RuntimeContext in practice)


class App(Protocol):
    """Lifecycle protocol every v1.0 app must satisfy."""

    async def mount(self, context: AppContext) -> None:
        """Build lightweight objects only: no big file reads, no hardware."""

    async def enter(self, route: RouteState) -> None:
        """Become foreground; load the data this screen needs."""

    def handle_input(self, event: Any) -> None:
        """Mutate state or dispatch commands only — no blocking I/O."""

    def update(self, delta_seconds: float) -> None:
        """Pure state update — no disk, network, database or subprocess."""

    def render(self, surface: pygame.Surface) -> None:
        """Pure rendering."""

    async def leave(self, reason: LeaveReason) -> None:
        """Cancel tasks and drop large caches before handing over."""

    async def dispose(self) -> None:
        """Unregister commands, events and hardware sessions."""
