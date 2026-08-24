from __future__ import annotations

import pytest

from deskcamdio.core.runtime import (
    LEGAL_TRANSITIONS,
    IllegalTransition,
    RunState,
    RuntimeStateMachine,
)


def test_boot_reaches_standby_then_launcher() -> None:
    machine = RuntimeStateMachine()
    assert machine.state is RunState.BOOT_LOGO

    machine.transition(RunState.STANDBY, reason="boot done")
    machine.transition(RunState.LAUNCHER)
    assert machine.state is RunState.LAUNCHER


def test_foreground_application_cycle() -> None:
    machine = RuntimeStateMachine(initial=RunState.LAUNCHER)
    machine.transition(RunState.APP)
    machine.transition(RunState.CAMERA_STARTING)
    machine.transition(RunState.APP, reason="camera ready")
    machine.transition(RunState.LAUNCHER)
    assert machine.return_state is RunState.LAUNCHER


def test_overlay_states_return_to_previous_foreground() -> None:
    machine = RuntimeStateMachine(initial=RunState.STANDBY)
    machine.transition(RunState.VOICE_SESSION)
    assert machine.return_state is RunState.STANDBY
    machine.transition(RunState.STANDBY)

    machine.transition(RunState.LAUNCHER)
    machine.transition(RunState.SCREEN_SLEEP)
    assert machine.return_state is RunState.LAUNCHER
    machine.transition(RunState.LAUNCHER)


def test_external_game_roundtrip() -> None:
    machine = RuntimeStateMachine(initial=RunState.LAUNCHER)
    machine.transition(RunState.EXTERNAL_GAME)
    machine.transition(RunState.SOFT_SLEEP)
    machine.transition(RunState.LAUNCHER)
    assert machine.state is RunState.LAUNCHER


def test_shutdown_is_terminal() -> None:
    machine = RuntimeStateMachine(initial=RunState.APP)
    machine.transition(RunState.SHUTTING_DOWN)
    with pytest.raises(IllegalTransition):
        machine.transition(RunState.STANDBY)


@pytest.mark.parametrize(
    ("source", "target"),
    [
        (RunState.BOOT_LOGO, RunState.LAUNCHER),
        (RunState.STANDBY, RunState.APP),
        (RunState.STANDBY, RunState.EXTERNAL_GAME),
        (RunState.LAUNCHER, RunState.CAMERA_STARTING),
        (RunState.CAMERA_STARTING, RunState.VOICE_SESSION),
        (RunState.VOICE_SESSION, RunState.EXTERNAL_GAME),
        (RunState.SCREEN_SLEEP, RunState.SOFT_SLEEP),
    ],
)
def test_illegal_transitions_raise(source: RunState, target: RunState) -> None:
    machine = RuntimeStateMachine(initial=source)
    with pytest.raises(IllegalTransition):
        machine.transition(target)
    assert machine.state is source


def test_every_state_has_a_transition_entry() -> None:
    for state in RunState:
        assert state in LEGAL_TRANSITIONS


def test_listeners_receive_changes_and_survive_errors() -> None:
    changes: list[str] = []
    machine = RuntimeStateMachine()

    def broken(_change: object) -> None:
        raise ValueError("boom")

    machine.subscribe(broken)
    machine.subscribe(lambda change: changes.append(change.current.name))

    machine.transition(RunState.STANDBY, reason="boot")
    assert changes == ["STANDBY"]
