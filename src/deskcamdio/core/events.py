"""Minimal synchronous pub/sub bus used by StateStore change events."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class Event:
    topic: str
    payload: dict[str, Any] = field(default_factory=dict)


class EventBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, list[Callable[[Event], None]]] = {}
        self._wildcards: list[Callable[[Event], None]] = []

    def subscribe(self, topic: str, callback: Callable[[Event], None]) -> Callable[[], None]:
        self._subscribers.setdefault(topic, []).append(callback)

        def unsubscribe() -> None:
            listeners = self._subscribers.get(topic)
            if listeners and callback in listeners:
                listeners.remove(callback)

        return unsubscribe

    def subscribe_all(self, callback: Callable[[Event], None]) -> Callable[[], None]:
        self._wildcards.append(callback)

        def unsubscribe() -> None:
            if callback in self._wildcards:
                self._wildcards.remove(callback)

        return unsubscribe

    def publish(self, topic: str, **payload: Any) -> None:
        event = Event(topic=topic, payload=payload)
        for callback in [*self._wildcards, *self._subscribers.get(topic, [])]:
            try:
                callback(event)
            except Exception:  # noqa: BLE001 - subscriber bugs must not break publishers
                LOGGER.exception("event listener failed for %s", topic)
