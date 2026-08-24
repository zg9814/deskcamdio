from __future__ import annotations

import dataclasses

import pygame
import pytest

from deskcamdio.core.lifecycle import LeaveReason, RouteState


def test_route_state_is_immutable() -> None:
    route = RouteState(app_id="camera")
    with pytest.raises(dataclasses.FrozenInstanceError):
        route.app_id = "gallery"  # type: ignore[misc]


def test_route_state_default_args_are_independent() -> None:
    first = RouteState(app_id="music")
    second = RouteState(app_id="music")
    assert first.args == second.args == {}


def test_leave_reasons_cover_guide_cases() -> None:
    names = {reason.name for reason in LeaveReason}
    assert {"NAVIGATED_BACK", "SUPERSEDED", "FAULT", "TIMEOUT", "SHUTDOWN"} <= names


def test_pygame_event_accepted_by_protocol_shape() -> None:
    event = pygame.event.Event(pygame.NOEVENT)
    assert event.type == pygame.NOEVENT
