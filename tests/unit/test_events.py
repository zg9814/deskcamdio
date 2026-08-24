from __future__ import annotations

from deskcamdio.core.events import EventBus


def test_wildcard_receives_all_topics() -> None:
    bus = EventBus()
    seen: list[str] = []
    unsubscribe = bus.subscribe_all(lambda event: seen.append(event.topic))
    bus.publish("a.changed", x=1)
    bus.publish("b.changed")
    assert seen == ["a.changed", "b.changed"]
    unsubscribe()
    bus.publish("c.changed")
    assert seen == ["a.changed", "b.changed"]


def test_topic_unsubscribe_is_idempotent() -> None:
    bus = EventBus()
    calls: list[int] = []
    off = bus.subscribe("t", lambda _e: calls.append(1))
    off()
    off()  # second call must not raise
    bus.publish("t")
    assert calls == []


def test_listener_exception_does_not_break_publishers() -> None:
    bus = EventBus()

    def boom(_event: object) -> None:
        raise RuntimeError("listener boom")

    received: list[str] = []
    bus.subscribe("t", boom)
    bus.subscribe("t", lambda _e: received.append("ok"))
    bus.publish("t")
    assert received == ["ok"]


def test_event_payload_defaults_empty() -> None:
    bus = EventBus()
    captured: list[dict] = []
    bus.subscribe("t", lambda event: captured.append(event.payload))
    bus.publish("t")
    assert captured == [{}]
