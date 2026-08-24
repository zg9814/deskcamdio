from __future__ import annotations

import asyncio
from pathlib import Path

import pygame

from deskcamdio.core.runtime import RunState


async def test_rc2_frame_rates_voice_and_ec11(tmp_path: Path) -> None:
    from test_input_flow import make_runtime

    runtime = await make_runtime(tmp_path)
    try:
        assert runtime.manager is not None and runtime.voice_service is not None
        standby = runtime.manager._mounted["standby"].app
        assert runtime._effective_frame_rate() == 60
        standby.low_power = True
        assert runtime._effective_frame_rate() == 5
        standby.low_power = False

        before = runtime.audio.volume_percent
        runtime.system = None
        runtime._on_hardware_input("volume_delta", 5)
        await asyncio.sleep(0)
        assert runtime.audio.volume_percent == min(100, before + 5)

        async def fake_turn():
            assert runtime.machine.state is RunState.VOICE_SESSION
            assert runtime._effective_frame_rate() == 15
            return "完成", {"action": "volume_up", "level": 37}

        runtime.voice_service.handle_turn = fake_turn  # type: ignore[method-assign]
        await runtime._voice_turn()
        assert runtime.machine.state is RunState.STANDBY
        assert runtime.audio.volume_percent == 37

        runtime._on_hardware_input("long_press", 1)
        assert runtime.machine.state is RunState.SOFT_SLEEP
        runtime._on_hardware_input("volume_delta", 5)
        await asyncio.sleep(0.02)
        assert runtime.machine.state is RunState.STANDBY
    finally:
        await runtime.shutdown()


async def test_rc2_standby_interactions_do_not_blank(tmp_path: Path) -> None:
    from test_input_flow import make_runtime

    runtime = await make_runtime(tmp_path)
    try:
        assert runtime.manager is not None
        app = runtime.manager._mounted["standby"].app
        surface = pygame.Surface((480, 480))
        app.render(surface)
        fish_pos = app._fish_position()
        for _ in range(8):
            app.handle_input(
                pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1, "pos": fish_pos})
            )
            app.handle_input(
                pygame.event.Event(pygame.MOUSEBUTTONUP, {"button": 1, "pos": fish_pos})
            )
        assert app._playing_dead > 0
        app.update(5.1)
        app.render(surface)
        assert surface.get_bounding_rect().width == 480

        app.low_power = True
        app.update(0.2)
        app.render(surface)
        app.low_power = False

        app.handle_input(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1, "pos": (450, 250)})
        )
        app.handle_input(pygame.event.Event(pygame.MOUSEBUTTONUP, {"button": 1, "pos": (350, 250)}))
        await asyncio.sleep(0.03)
        assert runtime.manager.active_id == "launcher"
    finally:
        await runtime.shutdown()


async def test_rc2_voice_action_handlers(tmp_path: Path) -> None:
    from test_input_flow import make_runtime

    runtime = await make_runtime(tmp_path)
    try:
        runtime._apply_voice_action({"action": "volume_mute"})
        assert runtime.audio.volume_percent == 0
        runtime._apply_voice_action({"action": "music.play"})
        runtime._apply_voice_action({"action": "music.pause"})
        runtime._apply_voice_action({"action": "memo.add", "body": "买牛奶"})
        runtime._apply_voice_action({"action": "memo.add", "body": ""})
        await asyncio.sleep(0.03)
        assert any(row["body"] == "买牛奶" for row in await runtime.store.list_memos())

        runtime._apply_voice_action({"action": "navigate", "app_id": "memo"})
        await asyncio.sleep(0.03)
        assert runtime.navigator_active() == "memo"
        runtime._apply_voice_action({"action": "navigate", "app_id": "missing"})
        runtime._apply_voice_action({"action": "unknown"})
    finally:
        await runtime.shutdown()


async def test_soft_sleep_quiesces_camera_and_fast_voice_cancel(tmp_path: Path) -> None:
    from test_input_flow import make_runtime

    runtime = await make_runtime(tmp_path)
    try:
        assert runtime.manager is not None and runtime.voice_service is not None
        runtime.launch_app("camera")
        await asyncio.sleep(0.08)
        assert runtime.manager.active_id == "camera"
        runtime._enter_soft_sleep()
        await asyncio.sleep(0.08)
        assert runtime.machine.state is RunState.SOFT_SLEEP
        assert runtime.manager.active_id == "standby"

        runtime._wake_display()
        runtime.voice_service.state = "idle"
        runtime.toggle_voice()
        runtime.toggle_voice()
        await asyncio.sleep(0)
        assert runtime.voice_service.state == "idle"

        class Session:
            stopped = 0

            def stop(self) -> None:
                self.stopped += 1

        session = Session()
        runtime.game_session = session
        runtime._on_hardware_input("controller_exit", 1)
        assert session.stopped == 1
        runtime.game_session = None
    finally:
        await runtime.shutdown()
