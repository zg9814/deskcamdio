"""Runtime run-state machine.

Phase A pins the legal transition graph between the ten unified runtime
states from DEVELOPMENT_GUIDE §2. Phase B builds DeviceRuntime on top of it.
Sleep-like states (voice/screen sleep/soft sleep) return to whatever
foreground state was active before; the machine records that automatically.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Any

import pygame

from deskcamdio._version import __version__
from deskcamdio.core import health as health_mod
from deskcamdio.core.app_manager import AppManager
from deskcamdio.core.events import EventBus
from deskcamdio.core.lifecycle import LeaveReason, RouteState
from deskcamdio.ui.themes import ThemeService

LOGGER = logging.getLogger(__name__)


class RunState(Enum):
    """Unified runtime states (DEVELOPMENT_GUIDE §2)."""

    BOOT_LOGO = auto()
    STANDBY = auto()
    LAUNCHER = auto()
    APP = auto()
    CAMERA_STARTING = auto()
    VOICE_SESSION = auto()
    EXTERNAL_GAME = auto()
    SCREEN_SLEEP = auto()
    SOFT_SLEEP = auto()
    SHUTTING_DOWN = auto()


_FOREGROUND = frozenset(
    {
        RunState.STANDBY,
        RunState.LAUNCHER,
        RunState.APP,
    }
)
_INTERACTIVE = _FOREGROUND | {
    RunState.CAMERA_STARTING,
}

#: Legal edges of the run-state graph. Anything not listed is a bug and must
#: raise instead of happening silently.
LEGAL_TRANSITIONS: dict[RunState, frozenset[RunState]] = {
    RunState.BOOT_LOGO: frozenset({RunState.STANDBY}),
    RunState.STANDBY: frozenset(
        {
            RunState.LAUNCHER,
            RunState.VOICE_SESSION,
            RunState.SCREEN_SLEEP,
            RunState.SOFT_SLEEP,
            RunState.SHUTTING_DOWN,
        }
    ),
    RunState.LAUNCHER: frozenset(
        {
            RunState.APP,
            RunState.STANDBY,
            RunState.EXTERNAL_GAME,
            RunState.VOICE_SESSION,
            RunState.SCREEN_SLEEP,
            RunState.SOFT_SLEEP,
            RunState.SHUTTING_DOWN,
        }
    ),
    RunState.APP: frozenset(
        {
            RunState.LAUNCHER,
            RunState.CAMERA_STARTING,
            RunState.EXTERNAL_GAME,
            RunState.VOICE_SESSION,
            RunState.SCREEN_SLEEP,
            RunState.SOFT_SLEEP,
            RunState.SHUTTING_DOWN,
        }
    ),
    # Camera worker spawn/failure happens while the camera page stays mounted;
    # CAMERA_STARTING always returns to APP or bails to LAUNCHER.
    RunState.CAMERA_STARTING: frozenset({RunState.APP, RunState.LAUNCHER, RunState.SHUTTING_DOWN}),
    RunState.VOICE_SESSION: _FOREGROUND | {RunState.SHUTTING_DOWN},
    RunState.EXTERNAL_GAME: frozenset(
        {RunState.LAUNCHER, RunState.SOFT_SLEEP, RunState.SHUTTING_DOWN}
    ),
    RunState.SCREEN_SLEEP: _FOREGROUND | {RunState.SHUTTING_DOWN},
    RunState.SOFT_SLEEP: _FOREGROUND | {RunState.SHUTTING_DOWN},
    RunState.SHUTTING_DOWN: frozenset(),
}

#: States that remember where they came from so wake-up can restore it.
_OVERLAY_STATES = frozenset(
    {
        RunState.VOICE_SESSION,
        RunState.SCREEN_SLEEP,
        RunState.SOFT_SLEEP,
    }
)


class IllegalTransition(RuntimeError):
    """Raised when a state change is not part of LEGAL_TRANSITIONS."""


@dataclass(frozen=True)
class StateChange:
    """One completed transition, broadcast to listeners."""

    previous: RunState
    current: RunState
    reason: str


class RuntimeStateMachine:
    """Validated, observable holder of the current run state."""

    def __init__(self, initial: RunState = RunState.BOOT_LOGO) -> None:
        self._state = initial
        self._return_state = initial
        self._listeners: list[Callable[[StateChange], None]] = []

    @property
    def state(self) -> RunState:
        return self._state

    @property
    def return_state(self) -> RunState:
        """Foreground state an overlay should hand control back to."""
        return self._return_state

    def subscribe(self, listener: Callable[[StateChange], None]) -> None:
        self._listeners.append(listener)

    def can_transition(self, target: RunState) -> bool:
        return target in LEGAL_TRANSITIONS[self._state]

    def transition(self, target: RunState, reason: str = "") -> StateChange:
        if target not in LEGAL_TRANSITIONS[self._state]:
            raise IllegalTransition(
                f"{self._state.name} -> {target.name} is not allowed"
                + (f" ({reason})" if reason else "")
            )
        change = StateChange(previous=self._state, current=target, reason=reason)
        if target in _OVERLAY_STATES:
            self._return_state = self._state
        elif target in _INTERACTIVE:
            self._return_state = target
        self._state = target
        for listener in self._listeners:
            try:
                listener(change)
            except Exception:  # noqa: BLE001 - listeners must never break the loop
                LOGGER.exception("state-change listener failed")
        LOGGER.info("event=run_state_change from=%s to=%s", change.previous.name, target.name)
        return change


SCREEN_SIZE = (480, 480)
DEFAULT_FPS = 30
HEALTH_INTERVAL = 5.0
BACK_KEYS = {pygame.K_ESCAPE, pygame.K_AC_BACK}


@dataclass
class RuntimeContext:
    """Service bundle handed to every app at mount."""

    store: Any
    bus: EventBus
    machine: RuntimeStateMachine
    audio: Any
    data_dir: Path
    launch: Callable[[str], None] | None = None
    run_dir: Path | None = None
    scope: Any = None  # TaskScope for this app instance
    system: Any = None  # SystemControlPort (wifi/bt/brightness/volume)
    theme: Any = field(default_factory=ThemeService)  # shared ThemeService
    app_catalog: tuple[Any, ...] = ()
    hardware_input: Any = None

    @property
    def effective_run_dir(self) -> Path:
        return self.run_dir if self.run_dir is not None else self.data_dir / "run"


class DeviceRuntime:
    """Owns the display loop, services and application lifecycle."""

    def __init__(
        self,
        *,
        data_dir: Path,
        run_dir: Path | None = None,
        apps_root: Path | None = None,
        headless: bool = False,
        fps: int = DEFAULT_FPS,
        health_interval: float = HEALTH_INTERVAL,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.run_dir = Path(run_dir) if run_dir else self.data_dir / "run"
        self.headless = headless
        self.target_fps = max(1, min(fps, 60))
        default_root = Path(__file__).resolve().parents[1] / "apps"
        self.apps_root = Path(apps_root) if apps_root else default_root
        self.health_interval = health_interval

        self.bus = EventBus()
        self.machine = RuntimeStateMachine()
        self.store: Any = None
        self.audio: Any = None
        self.manager: AppManager | None = None
        self.screen: pygame.Surface | None = None
        self.clock: pygame.time.Clock | None = None
        self.running = False
        self.frame_ms_history: list[float] = []
        self.last_frame_ms = 0.0
        self._touch_relay: Any = None
        self.last_error = ""
        self.voice_service: Any = None
        self._voice_task: asyncio.Task[None] | None = None
        self.system: Any = None
        self.theme: Any = None
        self.hardware_input: Any = None
        self.game_session: Any = None
        self._game_poll_task: asyncio.Task[None] | None = None
        self._game_display_suspended = False
        self._controller_monitor: Any = None
        self._soft_sleep_task: asyncio.Task[None] | None = None
        self._toast_text = ""
        self._toast_until = 0.0
        self._back_button_rect = pygame.Rect(428, 428, 52, 52)
        self._edge_swipe_start: tuple[int, int] | None = None
        self._touch_feedback_start: tuple[int, int] | None = None
        self._touch_feedback_moved = False
        self._workers: dict[str, str] = {}
        self._health_task: asyncio.Task[None] | None = None
        self._system_status_task: asyncio.Task[None] | None = None
        self._system_overlay: Any = None
        self._software_brightness = 100
        self._software_dimming_enabled = False
        self._dimming_surface = pygame.Surface(SCREEN_SIZE, pygame.SRCALPHA)

    # ---- lifecycle -------------------------------------------------------

    async def initialize(self) -> None:
        if self.headless:
            os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
            os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
        flags = pygame.HIDDEN if self.headless else 0
        pygame.display.init()
        pygame.font.init()
        self.screen = pygame.display.set_mode(SCREEN_SIZE, flags)
        self.clock = pygame.time.Clock()
        self._render_boot_logo()

        if not self.headless and os.getenv("DESKCAMDIO_PLATFORM") == "raspberry_pi":
            from deskcamdio.services.touch_relay import TouchRelay, discover_touch_device

            touch_path = discover_touch_device()
            if touch_path is not None:
                self._touch_relay = TouchRelay(touch_path, SCREEN_SIZE)
                self._touch_relay.start()
                self._touch_relay.ready.wait(0.25)
                if self._touch_relay.ready.is_set() and not self._touch_relay.grabbed:
                    self._touch_relay.stop()
                    self._touch_relay = None
                    LOGGER.info("event=touch_relay_disabled native_sdl=true")
            else:
                LOGGER.warning("event=touch_device_not_found")

        from deskcamdio.services.audio import AudioService

        self.audio = AudioService()

        from deskcamdio.services.state_store import open_store

        self.store = await open_store(self.data_dir / "state.db", self.bus)
        from deskcamdio.ui.themes import DEFAULT_THEME_ID, ThemeService

        self.theme = ThemeService(str(await self.store.get_setting("theme", DEFAULT_THEME_ID)))

        def context_factory(app_id: str, scope: Any) -> RuntimeContext:
            del app_id
            return RuntimeContext(
                store=self.store,
                bus=self.bus,
                machine=self.machine,
                audio=self.audio,
                data_dir=self.data_dir,
                launch=self.launch_app,
                run_dir=self.run_dir,
                scope=scope,
                system=self.system,
                theme=self.theme,
                app_catalog=tuple(self.manager.descriptors.values()) if self.manager else (),
                hardware_input=self.hardware_input,
            )

        self.manager = AppManager(
            bus=self.bus, context_factory=context_factory, apps_root=self.apps_root
        )
        self.audio.load_volume(await self.store.get_setting("volume", 80))
        self.voice_service = self._build_voice_service()
        from deskcamdio.platform.system import create_system_control

        self.system = create_system_control()
        await asyncio.to_thread(self.system.set_system_volume, self.audio.volume_percent)
        self._software_dimming_enabled = not await asyncio.to_thread(
            self.system.has_hardware_brightness
        )
        stored_brightness = int(await self.store.get_setting("brightness", 100))
        if self._software_dimming_enabled:
            self._set_software_brightness(stored_brightness)
        from deskcamdio.ui.system_overlay import SystemOverlay

        self._system_overlay = SystemOverlay(
            volume=self.audio.volume_percent,
            brightness=(self._software_brightness if self._software_dimming_enabled else 80),
        )
        from deskcamdio.services.hardware_input import create_hardware_input

        self.hardware_input = create_hardware_input()
        loop = asyncio.get_running_loop()
        self.hardware_input.subscribe(
            lambda name, value: loop.call_soon_threadsafe(self._on_hardware_input, name, value)
        )
        self._screen_timeout = int(await self.store.get_setting("screen_timeout_seconds", 0))
        self._last_activity = time.monotonic()
        self.bus.subscribe("settings.changed", self._on_settings_changed)
        self.bus.subscribe("gba.launch_requested", self._on_game_launch_requested)
        self.bus.subscribe("ps1.launch_requested", self._on_ps1_launch_requested)
        self.bus.subscribe("voice.toggle", lambda _event: self.toggle_voice())
        self.bus.subscribe("app.fault", self._on_app_fault)
        await self._enter_standby()
        self.running = True
        self._health_task = asyncio.get_running_loop().create_task(
            self._health_loop(), name="runtime:health"
        )
        self._system_status_task = asyncio.get_running_loop().create_task(
            self._system_status_loop(), name="runtime:system-status"
        )
        LOGGER.info("event=runtime_started version=%s", __version__)

    async def _enter_standby(self) -> None:
        assert self.manager is not None
        if self.machine.state is not RunState.STANDBY:
            self.machine.transition(RunState.STANDBY, reason="boot")
        await self.manager.enter(RouteState(app_id="standby"))

    def _on_settings_changed(self, event: Any) -> None:
        key = event.payload.get("key")
        if key == "screen_timeout_seconds":
            asyncio.get_running_loop().create_task(self._reload_screen_timeout())
        elif key == "theme" and self.theme is not None:
            with contextlib.suppress(ValueError):
                self.theme.select(str(event.payload.get("value", "aquatic")))

    def _on_app_fault(self, event: Any) -> None:
        self.last_error = f"app fault: {event.payload.get('app', 'unknown')}"
        state = self.machine.state
        if state is RunState.APP:
            self.machine.transition(RunState.LAUNCHER, reason="app fault")
            self.machine.transition(RunState.STANDBY, reason="fault fallback")
        elif state is RunState.CAMERA_STARTING:
            self.machine.transition(RunState.LAUNCHER, reason="camera fault")
            self.machine.transition(RunState.STANDBY, reason="fault fallback")
        elif state is RunState.LAUNCHER:
            self.machine.transition(RunState.STANDBY, reason="fault fallback")

    async def _reload_screen_timeout(self) -> None:
        assert self.store is not None
        self._screen_timeout = int(await self.store.get_setting("screen_timeout_seconds", 0))

    def _note_activity(self) -> None:
        self._last_activity = time.monotonic()
        if self.machine.state is RunState.SCREEN_SLEEP:
            wake = self.machine.return_state
            if self.machine.can_transition(wake):
                self.machine.transition(wake, reason="wake")

    def _on_hardware_input(self, name: str, value: int) -> None:
        """Route EC11 callbacks on the asyncio/pygame owner thread."""
        if self.machine.state in (RunState.SCREEN_SLEEP, RunState.SOFT_SLEEP):
            self._wake_display()
            return
        self._note_activity()
        if name == "volume_delta":
            target = int(self.audio.volume_percent) + value
            self.audio.set_volume(target)
            if self.system is not None:
                asyncio.create_task(asyncio.to_thread(self.system.set_system_volume, target))
            asyncio.create_task(self.store.set_setting("volume", self.audio.volume_percent))
            self.show_toast(f"音量 {self.audio.volume_percent}")
        elif name == "short_press":
            if self.machine.state is RunState.EXTERNAL_GAME and self.game_session is not None:
                self.game_session.request_stop("ec11")
            elif self.navigator_active() == "camera":
                self._action_camera_capture({})
            else:
                self.toggle_voice()
        elif name == "long_press":
            self._enter_soft_sleep()
        elif name == "controller_exit" and self.game_session is not None:
            self.game_session.request_stop("controller")

    def _set_display_power(self, enabled: bool) -> None:
        import subprocess

        with contextlib.suppress(OSError, subprocess.TimeoutExpired):
            subprocess.run(
                ["vcgencmd", "display_power", "1" if enabled else "0"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=2,
            )

    def _render_boot_logo(self) -> None:
        if self.screen is None:
            return
        self.screen.fill((8, 10, 14))
        font = pygame.font.Font(None, 78)
        wordmark = font.render("Fish", True, (226, 56, 64))
        self.screen.blit(wordmark, wordmark.get_rect(center=(240, 228)))
        line = pygame.Rect(168, 276, 144, 3)
        pygame.draw.rect(self.screen, (226, 56, 64), line)
        pygame.display.flip()

    def _enter_soft_sleep(self) -> None:
        if self.machine.state is RunState.SOFT_SLEEP:
            return
        if self.machine.state is RunState.EXTERNAL_GAME and self.game_session is not None:
            self.game_session.request_stop("soft-sleep")
            return
        if self.voice_service is not None:
            self.voice_service.cancel()
        if self.audio is not None:
            self.audio.pause_music()
            self.audio.close()
        if self.screen is not None:
            self.screen.fill((0, 0, 0))
            pygame.display.flip()
        if self.machine.can_transition(RunState.SOFT_SLEEP):
            self.machine.transition(RunState.SOFT_SLEEP, reason="ec11 long press")
        if self.manager is not None and self.manager.active_id != "standby":
            self._soft_sleep_task = asyncio.create_task(self._quiesce_for_soft_sleep())
        self._set_display_power(False)

    async def _quiesce_for_soft_sleep(self) -> None:
        assert self.manager is not None
        try:
            await self.manager.enter(RouteState(app_id="standby"), LeaveReason.SUPERSEDED)
        finally:
            self._soft_sleep_task = None

    def _wake_display(self) -> None:
        self._set_display_power(True)
        self._render_boot_logo()
        target = RunState.STANDBY
        if self.machine.can_transition(target):
            self.machine.transition(target, reason="hardware wake")
        self._spawn_enter("standby")
        self._toast_text = "Fish"
        self._toast_until = time.monotonic() + 1.6

    async def run(self, frame_limit: int | None = None) -> None:
        assert self.manager is not None and self.screen is not None and self.clock is not None, (
            "initialize() first"
        )
        frames = 0
        try:
            while self.running:
                started = time.monotonic()
                frame_rate = self._effective_frame_rate()
                self._pump_events()
                if (
                    self.machine.state in (RunState.STANDBY, RunState.LAUNCHER, RunState.APP)
                    and self._screen_timeout > 0
                    and time.monotonic() - self._last_activity >= self._screen_timeout
                    and self.voice_service is not None
                    and self.voice_service.state == "idle"
                ):
                    self.machine.transition(RunState.SCREEN_SLEEP, reason="idle timeout")
                    continue

                if self.machine.state in (
                    RunState.SCREEN_SLEEP,
                    RunState.SOFT_SLEEP,
                    RunState.EXTERNAL_GAME,
                ):
                    # mGBA owns the display during EXTERNAL_GAME; UI is frozen.
                    await asyncio.sleep(0.2 if self.machine.state is RunState.SOFT_SLEEP else 0.05)
                elif self.machine.state is not RunState.SHUTTING_DOWN:
                    self.manager.update(1 / frame_rate)
                    if self._system_overlay is not None:
                        self._system_overlay.update(1 / frame_rate)
                    self.screen.fill((8, 12, 18))
                    self.manager.render(self.screen)
                    self._render_global_back(self.screen)
                    if self._system_overlay is not None:
                        self._system_overlay.render(self.screen, self.theme.tokens)
                    self._render_toast(self.screen)
                    self._render_software_dimming(self.screen)
                    pygame.display.flip()
                self.last_frame_ms = (time.monotonic() - started) * 1000
                self.frame_ms_history.append(self.last_frame_ms)
                frames += 1
                if frame_limit is not None and frames >= frame_limit:
                    break
                self.clock.tick(frame_rate)
                await asyncio.sleep(0)
        finally:
            await self.shutdown()

    def _effective_frame_rate(self) -> int:
        if self.machine.state is RunState.VOICE_SESSION:
            return min(15, self.target_fps)
        if self._system_overlay is not None and (
            self._system_overlay.animating or self._system_overlay.interacting
        ):
            return max(60, self.target_fps)
        if self.manager is not None and self.manager.active_id == "standby":
            mounted = self.manager._mounted.get("standby")  # noqa: SLF001
            if mounted is not None and bool(getattr(mounted.app, "low_power", False)):
                return min(5, self.target_fps)
        if self.manager is not None:
            preferred = self.manager.preferred_fps()
            if preferred is not None:
                return max(self.target_fps, preferred)
        return self.target_fps

    # ---- voice -------------------------------------------------------------

    def _build_voice_service(self) -> Any:
        from deskcamdio.services.backend_client import BackendClient
        from deskcamdio.services.voice import (
            LocalCommandRouter,
            VoiceService,
            is_local_asr_mode,
        )

        backend = BackendClient(
            os.getenv("DESKCAMDIO_BACKEND_URL", "http://127.0.0.1:8000"),
            access_token=os.getenv("DESKCAMDIO_BACKEND_TOKEN", ""),
        )
        model_dir_env = os.getenv("DESKCAMDIO_ASR_MODEL_DIR", "")
        return VoiceService(
            backend,
            LocalCommandRouter(),
            data_dir=self.data_dir,
            model_dir=Path(model_dir_env) if model_dir_env else None,
            use_local_asr=is_local_asr_mode(os.getenv("DESKCAMDIO_ASR_MODE")),
        )

    def toggle_voice(self) -> None:
        """Short press: start a turn; another press while busy cancels it."""
        service = self.voice_service
        if service is None:
            return
        if self._voice_task is not None and not self._voice_task.done():
            if service.state == "starting":
                self._voice_task.cancel()
                self._voice_task = None
                service.state = "idle"
            else:
                service.cancel()
            self.show_toast("语音已取消")
            return
        if service.state != "idle":
            service.cancel()
            self.show_toast("语音已取消")
            return
        service.state = "starting"
        self._voice_task = asyncio.get_running_loop().create_task(
            self._voice_turn(), name="runtime:voice-turn"
        )

    async def _voice_turn(self) -> None:
        service = self.voice_service
        assert service is not None
        was_playing = bool(getattr(self.audio, "music_playing", False))
        entered_voice_state = self.machine.can_transition(RunState.VOICE_SESSION)
        if entered_voice_state:
            self.machine.transition(RunState.VOICE_SESSION, reason="voice started")
        if was_playing:
            self.audio.pause_music()
        reply = ""
        action: dict[str, Any] | None = None
        try:
            reply, action = await service.handle_turn()
        finally:
            if entered_voice_state and self.machine.state is RunState.VOICE_SESSION:
                target = self.machine.return_state
                if self.machine.can_transition(target):
                    self.machine.transition(target, reason="voice finished")
            if was_playing and not self.audio.music_playing:
                self.audio.resume_music()
            self._voice_task = None
        if reply:
            self.show_toast(reply)
        if action is not None:
            self._apply_voice_action(action)
        if reply and os.getenv("DESKCAMDIO_TTS") == "1":
            with contextlib.suppress(Exception):
                await self._play_tts(reply)

    def _apply_voice_action(self, payload: dict[str, Any]) -> None:
        handlers: dict[str, Callable[[dict[str, Any]], None]] = {
            "navigate": self._action_navigate,
            "volume_up": self._action_volume_up,
            "volume_mute": self._action_volume_mute,
            "music.play": lambda _p: self.audio.resume_music(),
            "music.pause": lambda _p: self.audio.pause_music(),
            "timer.start": self._action_timer_start,
            "memo.add": self._action_memo_add,
            "camera.capture": self._action_camera_capture,
            "network.report": self._queue_network_report,
        }
        name = str(payload.get("action", ""))
        handler = handlers.get(name)
        if handler is not None:
            handler(payload)

    def _action_navigate(self, payload: dict[str, Any]) -> None:
        app_id = str(payload.get("app_id", ""))
        try:
            self.launch_app(app_id)
        except KeyError:
            self.show_toast(f"未知应用 {app_id}")

    def _action_volume_up(self, payload: dict[str, Any]) -> None:
        level = payload.get("level")
        target = int(level) if level else int(self.audio.volume_percent) + 10
        self.audio.set_volume(target)
        self.show_toast(f"音量 {self.audio.volume_percent}")
        asyncio.get_running_loop().create_task(
            self.store.set_setting("volume", self.audio.volume_percent)
        )

    def _action_volume_mute(self, _payload: dict[str, Any]) -> None:
        self.audio.set_volume(0)
        self.show_toast("已静音")
        asyncio.get_running_loop().create_task(self.store.set_setting("volume", 0))

    def _action_timer_start(self, payload: dict[str, Any]) -> None:
        minutes = int(payload.get("minutes", 25))
        self.launch_app("pomodoro")
        self.bus.publish("pomodoro.configure", minutes=minutes)
        self.show_toast(f"{minutes} 分钟倒计时")

    def _action_memo_add(self, payload: dict[str, Any]) -> None:
        body = str(payload.get("body", "")).strip()
        if not body:
            return
        asyncio.get_running_loop().create_task(self.store.add_memo(body))
        self.show_toast("备忘已添加")

    def _action_camera_capture(self, _payload: dict[str, Any]) -> None:
        if self.navigator_active() == "camera" and self.manager is not None:
            host = self.manager._mounted.get("camera")  # noqa: SLF001 - internal route
            capture = getattr(host.app, "_capture", None) if host else None
            if callable(capture):
                asyncio.get_running_loop().create_task(capture())
        else:
            self.launch_app("camera")

    async def _action_network_report(self) -> None:
        if self.system is None:
            self.show_toast("设备状态不可用")
            return
        wifi, bluetooth = await asyncio.gather(
            asyncio.to_thread(self.system.wifi_status),
            asyncio.to_thread(self.system.bluetooth_status),
        )
        net = str(wifi.get("ssid", "未连接")) if wifi.get("connected") else "未连接"
        bt = "开" if bluetooth.get("powered") else "关"
        self.show_toast(f"Wi-Fi {net} · 蓝牙{bt}")

    def _queue_network_report(self, _payload: dict[str, Any]) -> None:
        asyncio.create_task(self._action_network_report())

    def navigator_active(self) -> str:
        return self.manager.active_id if self.manager else ""

    async def _play_tts(self, text: str) -> None:
        assert self.voice_service is not None
        import shutil

        aplay = shutil.which("aplay")

        async def consume(stream: AsyncIterator[bytes], media_type: str) -> None:
            if aplay is None:
                async for _chunk in stream:
                    pass
                return
            args = [aplay, "-q"]
            if "L16" in media_type.upper():
                args += ["-t", "raw", "-f", "S16_LE", "-r", "16000", "-c", "1"]
            process = await asyncio.create_subprocess_exec(
                *args, stdin=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
            )
            assert process.stdin is not None
            try:
                async for chunk in stream:
                    process.stdin.write(chunk)
                    await process.stdin.drain()
            finally:
                process.stdin.close()
                with contextlib.suppress(Exception):
                    await process.stdin.wait_closed()
                await process.wait()

        await self.voice_service.backend.stream_tts(text, consume)

    # ---- toast ---------------------------------------------------------------

    def show_toast(self, text: str, seconds: float = 3.0) -> None:
        self._toast_text = text
        self._toast_until = time.monotonic() + seconds
        LOGGER.info("event=toast text=%s", text)

    def _render_toast(self, surface: pygame.Surface) -> None:
        if not self._toast_text or time.monotonic() >= self._toast_until:
            return
        from deskcamdio.ui.typography import draw_wrapped

        theme = self.theme.tokens
        banner = pygame.Rect(36, 382, 408, 88)
        pygame.draw.rect(surface, (*theme.surface_elevated, 230), banner, border_radius=12)
        draw_wrapped(
            surface,
            self._toast_text[:120],
            banner.inflate(-24, -16),
            17,
            (255, 255, 255),
            line_gap=4,
        )

    # ---- GBA session wiring ----------------------------------------------------

    def _on_game_launch_requested(self, event: Any) -> None:
        sha256 = str(event.payload.get("sha256", ""))
        asyncio.get_running_loop().create_task(self._start_game(sha256))

    def _on_ps1_launch_requested(self, event: Any) -> None:
        path = str(event.payload.get("path", ""))
        asyncio.get_running_loop().create_task(self._start_ps1_game(path))

    async def _enter_route(self, app_id: str) -> None:
        assert self.manager is not None
        await self.manager.enter(RouteState(app_id=app_id))

    async def _start_game(self, sha256: str) -> None:
        assert self.store is not None
        if self.machine.state not in (RunState.LAUNCHER, RunState.APP):
            return
        row = await self.store.fetch_one("SELECT path FROM gba_roms WHERE sha256=?", (sha256,))
        if row is None:
            self.show_toast("ROM 未索引，请刷新游戏库")
            return
        from deskcamdio.services.game_session import (
            ControllerMonitor,
            GameSession,
            ensure_mgba,
            find_mgba,
        )

        binary = find_mgba()
        try:
            ensure_mgba(binary)
        except Exception as exc:  # noqa: BLE001 - missing binary is user-facing
            self.show_toast(str(exc))
            return

        mapping = str(await self.store.get_setting("controller_mapping", ""))
        was_playing = bool(getattr(self.audio, "music_playing", False))
        if was_playing:
            self.audio.pause_music()
        session = GameSession(
            binary,
            Path(str(row[0])),
            self.data_dir / "saves" / "gba",
            controller_config=mapping,
        )
        self._suspend_display_for_game()
        try:
            session.start()
        except Exception as exc:  # noqa: BLE001
            self._restore_display_after_game()
            self.show_toast(f"启动失败：{exc}")
            if was_playing:
                self.audio.resume_music()
            return

        self.game_session = session
        self._controller_monitor = ControllerMonitor(session)
        self._controller_monitor.start()
        self.machine.transition(RunState.EXTERNAL_GAME, reason=f"rom:{sha256[:8]}")
        self._game_poll_task = asyncio.get_running_loop().create_task(self._watch_game(was_playing))
        self.show_toast("游戏中：四肩键同按 1 秒退出")

    async def _start_ps1_game(self, raw_path: str) -> None:
        if self.machine.state not in (RunState.LAUNCHER, RunState.APP):
            return
        content = Path(raw_path).resolve()
        library = (self.data_dir / "roms" / "ps1").resolve()
        if not content.is_file() or library not in content.parents:
            self.show_toast("PS1 游戏文件无效")
            return
        from deskcamdio.services.game_session import ControllerMonitor
        from deskcamdio.services.ps1_session import (
            DEFAULT_PCSX_CORE,
            DEFAULT_RETROARCH,
            RetroArchSession,
            ensure_ps1_runtime,
        )

        retroarch = Path(os.getenv("DESKCAMDIO_RETROARCH_BIN", str(DEFAULT_RETROARCH)))
        core = Path(os.getenv("DESKCAMDIO_PCSX_CORE", str(DEFAULT_PCSX_CORE)))
        try:
            ensure_ps1_runtime(retroarch, core)
        except Exception as exc:  # noqa: BLE001 - user-facing installation failure
            self.show_toast(str(exc))
            return
        was_playing = bool(getattr(self.audio, "music_playing", False))
        if was_playing:
            self.audio.pause_music()
        session = RetroArchSession(retroarch, core, content, self.data_dir)
        self._suspend_display_for_game()
        try:
            session.start()
        except Exception as exc:  # noqa: BLE001
            self._restore_display_after_game()
            self.show_toast(f"PS1 启动失败：{exc}")
            if was_playing:
                self.audio.resume_music()
            return
        self.game_session = session
        self._controller_monitor = ControllerMonitor(session)
        self._controller_monitor.start()
        self.machine.transition(RunState.EXTERNAL_GAME, reason=f"ps1:{content.stem[:24]}")
        self._game_poll_task = asyncio.get_running_loop().create_task(self._watch_game(was_playing))
        self.show_toast("PS1 游戏中：四肩键同按 1 秒退出")

    async def _watch_game(self, resume_music_after: bool) -> None:
        while self.game_session is not None:
            if self.game_session.poll():
                break
            if not self.game_session.running:
                break
            await asyncio.sleep(0.5)
        self._restore_display_after_game()
        if self.machine.state is RunState.EXTERNAL_GAME:
            self.machine.transition(RunState.LAUNCHER, reason="game exit")
            await self._enter_route("launcher")
        if resume_music_after:
            self.audio.resume_music()
        if self._controller_monitor is not None:
            self._controller_monitor.stop()
            self._controller_monitor = None
        self.game_session = None

    def _suspend_display_for_game(self) -> None:
        """Release the DRM master so the external mGBA SDL process can own it."""
        if self.headless or self._game_display_suspended:
            return
        pygame.display.quit()
        self._game_display_suspended = True

    def _restore_display_after_game(self) -> None:
        """Reacquire KMS and redraw a clean Fish frame after mGBA exits."""
        if not self._game_display_suspended:
            return
        pygame.display.init()
        self.screen = pygame.display.set_mode(SCREEN_SIZE)
        self._game_display_suspended = False
        self._render_boot_logo()

    # ---- input & navigation ----------------------------------------------

    def _pump_events(self) -> None:
        if self.machine.state is RunState.EXTERNAL_GAME and not pygame.display.get_init():
            # mGBA owns KMS. EC11/controller callbacks still arrive through
            # their dedicated threads, while pygame has no valid event queue.
            return
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.request_shutdown("quit")
                return
            if self._system_overlay is not None:
                overlay_action = self._system_overlay.handle_input(event)
                if overlay_action is not None:
                    self._handle_overlay_action(*overlay_action)
                    self._note_activity()
                    continue
            self._handle_touch_feedback(event)
            if event.type == pygame.KEYDOWN and event.key in BACK_KEYS:
                self.navigate_back()
                continue
            if self._handle_global_navigation(event):
                self._note_activity()
                continue
            if event.type in {
                pygame.KEYDOWN,
                pygame.MOUSEBUTTONDOWN,
                pygame.MOUSEMOTION,
                pygame.FINGERDOWN,
                pygame.FINGERMOTION,
            }:
                self._note_activity()
            foreground = {
                RunState.STANDBY,
                RunState.LAUNCHER,
                RunState.APP,
            }
            if self.manager is not None and self.machine.state in foreground:
                self.manager.handle_input(event)

    def _handle_overlay_action(self, action: str, value: int) -> None:
        if action.startswith("volume"):
            self.audio.set_volume(value)
            if action.endswith("_commit"):
                asyncio.create_task(self.store.set_setting("volume", value))
                asyncio.create_task(asyncio.to_thread(self.system.set_system_volume, value))
        elif action.startswith("brightness") and action.endswith("_commit"):
            asyncio.create_task(self.store.set_setting("brightness", value))
            asyncio.create_task(asyncio.to_thread(self.system.set_brightness, value))
        if action.startswith("brightness") and self._software_dimming_enabled:
            self._set_software_brightness(value)

    def _set_software_brightness(self, value: int) -> None:
        self._software_brightness = max(5, min(100, int(value)))
        alpha = round((100 - self._software_brightness) * 1.9)
        self._dimming_surface.fill((0, 0, 0, alpha))

    def _render_software_dimming(self, surface: pygame.Surface) -> None:
        if not self._software_dimming_enabled or self._software_brightness >= 100:
            return
        surface.blit(self._dimming_surface, (0, 0))

    def _handle_touch_feedback(self, event: pygame.event.Event) -> None:
        """Play one quiet UI tick for a completed tap, never for a swipe."""
        if self.machine.state not in {RunState.STANDBY, RunState.LAUNCHER, RunState.APP}:
            self._touch_feedback_start = None
            return
        if event.type == pygame.MOUSEBUTTONDOWN and getattr(event, "button", 1) == 1:
            self._touch_feedback_start = (int(event.pos[0]), int(event.pos[1]))
            self._touch_feedback_moved = False
            return
        if event.type == pygame.MOUSEMOTION and self._touch_feedback_start is not None:
            dx = int(event.pos[0]) - self._touch_feedback_start[0]
            dy = int(event.pos[1]) - self._touch_feedback_start[1]
            self._touch_feedback_moved = self._touch_feedback_moved or dx * dx + dy * dy > 576
            return
        if event.type != pygame.MOUSEBUTTONUP or self._touch_feedback_start is None:
            return
        dx = int(event.pos[0]) - self._touch_feedback_start[0]
        dy = int(event.pos[1]) - self._touch_feedback_start[1]
        if not self._touch_feedback_moved and dx * dx + dy * dy <= 576:
            self.audio.play_sound("tap", category="ui")
        self._touch_feedback_start = None
        self._touch_feedback_moved = False

    def _handle_global_navigation(self, event: pygame.event.Event) -> bool:
        """Android-like back affordance: edge button plus left-edge swipe."""
        if self.machine.state not in {RunState.APP, RunState.LAUNCHER}:
            self._edge_swipe_start = None
            return False
        if event.type == pygame.MOUSEBUTTONDOWN and getattr(event, "button", 1) == 1:
            pos = tuple(event.pos)
            if self._back_button_rect.collidepoint(pos):
                self.navigate_back()
                self._edge_swipe_start = None
                return True
            if pos[0] <= 24:
                self._edge_swipe_start = (int(pos[0]), int(pos[1]))
                return True
        elif event.type == pygame.MOUSEMOTION and self._edge_swipe_start is not None:
            return True
        elif event.type == pygame.MOUSEBUTTONUP and self._edge_swipe_start is not None:
            start = self._edge_swipe_start
            self._edge_swipe_start = None
            pos = tuple(event.pos)
            if pos[0] - start[0] >= 80 and abs(pos[1] - start[1]) <= 120:
                self.navigate_back()
            return True
        return False

    def _render_global_back(self, surface: pygame.Surface) -> None:
        if self.machine.state not in {RunState.APP, RunState.LAUNCHER}:
            return
        theme = self.theme.tokens if self.theme is not None else None
        fill = theme.surface_elevated if theme is not None else (32, 45, 58)
        stroke = theme.stroke if theme is not None else (100, 120, 138)
        arrow = theme.text_primary if theme is not None else (240, 244, 248)
        pygame.draw.rect(surface, fill, self._back_button_rect, border_top_left_radius=18)
        pygame.draw.rect(
            surface,
            stroke,
            self._back_button_rect,
            width=1,
            border_top_left_radius=18,
        )
        center_x, center_y = self._back_button_rect.center
        pygame.draw.line(
            surface, arrow, (center_x + 6, center_y - 10), (center_x - 6, center_y), width=4
        )
        pygame.draw.line(
            surface, arrow, (center_x - 6, center_y), (center_x + 6, center_y + 10), width=4
        )

    def navigate_back(self) -> None:
        state = self.machine.state
        if state is RunState.APP:
            self.machine.transition(RunState.LAUNCHER, reason="back")
            self._spawn_enter("launcher")
        elif state is RunState.LAUNCHER:
            self.machine.transition(RunState.STANDBY, reason="back")
            self._spawn_enter("standby")

    def launch_app(self, app_id: str) -> None:
        assert self.manager is not None
        if app_id not in self.manager.descriptor_ids():
            raise KeyError(app_id)
        state = self.machine.state
        if state is RunState.STANDBY and app_id == "launcher":
            self.machine.transition(RunState.LAUNCHER, reason="open launcher")
        elif state is RunState.STANDBY and app_id not in ("standby", "launcher"):
            self.machine.transition(RunState.LAUNCHER, reason="home shortcut")
            self.machine.transition(RunState.APP, reason=f"launch:{app_id}")
        elif state is RunState.LAUNCHER and app_id not in ("standby", "launcher"):
            self.machine.transition(RunState.APP, reason=f"launch:{app_id}")
        elif state is RunState.LAUNCHER and app_id == "standby":
            self.machine.transition(RunState.STANDBY, reason="home swipe")
        elif state is RunState.APP and app_id not in ("standby", "launcher"):
            self.machine.transition(RunState.LAUNCHER, reason="switch app")
            self.machine.transition(RunState.APP, reason=f"launch:{app_id}")
        else:
            return
        self._spawn_enter(app_id)

    def _spawn_enter(self, app_id: str) -> None:
        assert self.manager is not None
        manager = self.manager
        asyncio.get_running_loop().create_task(manager.enter(RouteState(app_id=app_id)))

    # ---- shutdown & health -------------------------------------------------

    def request_shutdown(self, reason: str) -> None:
        if self.machine.state is not RunState.SHUTTING_DOWN:
            try:
                self.machine.transition(RunState.SHUTTING_DOWN, reason=reason)
            except Exception:  # noqa: BLE001
                LOGGER.exception("shutdown transition rejected")
        self.running = False

    async def shutdown(self) -> None:  # noqa: C901
        if self._health_task is None and self.store is None and self.manager is None:
            return
        self.running = False
        if self._controller_monitor is not None:
            self._controller_monitor.stop()
            self._controller_monitor = None
        if self.game_session is not None:
            self.game_session.request_stop("shutdown")
            self.game_session = None
        if self._game_poll_task is not None:
            self._game_poll_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._game_poll_task
            self._game_poll_task = None
        if self._soft_sleep_task is not None:
            self._soft_sleep_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._soft_sleep_task
            self._soft_sleep_task = None
        if self._touch_relay is not None:
            self._touch_relay.stop()
            with contextlib.suppress(Exception):
                self._touch_relay.join(timeout=0.5)
            self._touch_relay = None
        if self.hardware_input is not None:
            self.hardware_input.close()
            self.hardware_input = None
        if self._voice_task is not None:
            self._voice_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._voice_task
            self._voice_task = None
        if self._health_task is not None:
            self._health_task.cancel()
            self._health_task = None
        if self._system_status_task is not None:
            self._system_status_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._system_status_task
            self._system_status_task = None
        if self.manager is not None:
            await self.manager.leave_current(LeaveReason.SHUTDOWN)
            await self.manager.dispose_all()
            self.manager = None
        if self.store is not None:
            await self.store.close()
            self.store = None
        if self.audio is not None:
            self.audio.close()
            self.audio = None
        if self.voice_service is not None:
            self.voice_service.cancel()
            close = getattr(self.voice_service.backend, "close", None)
            if callable(close):
                with contextlib.suppress(Exception):
                    await close()
            self.voice_service = None
        pygame.quit()
        LOGGER.info("event=runtime_stopped")

    async def _health_loop(self) -> None:
        while True:
            snapshot = health_mod.build_snapshot(
                version=__version__,
                active_app=self.manager.active_id if self.manager else "",
                mode=self.machine.state.name,
                workers=self._workers,
                last_frame_ms=self.last_frame_ms,
                last_error=self.last_error,
            )
            with contextlib.suppress(OSError):  # read-only fs on CI
                health_mod.write_health(self.run_dir / "health.json", snapshot)
            self._notify_watchdog()
            await asyncio.sleep(self.health_interval)

    async def _system_status_loop(self) -> None:
        while True:
            try:
                wifi, bluetooth, controller, brightness = await asyncio.gather(
                    asyncio.to_thread(self.system.wifi_status),
                    asyncio.to_thread(self.system.bluetooth_status),
                    asyncio.to_thread(self.system.controller_connected),
                    asyncio.to_thread(self.system.get_brightness),
                )
                if self._system_overlay is not None:
                    self._system_overlay.status.update(
                        {
                            "wifi": bool(wifi.get("connected")),
                            "ssid": str(wifi.get("ssid", "")),
                            "bluetooth": bool(bluetooth.get("powered")),
                            "controller": bool(controller),
                            "brightness": int(brightness),
                        }
                    )
                    if (
                        not self._software_dimming_enabled
                        and self._system_overlay.active_slider != "brightness"
                    ):
                        self._system_overlay.brightness = int(brightness)
                    if self._system_overlay.active_slider != "volume":
                        self._system_overlay.volume = int(self.audio.volume_percent)
            except Exception:  # noqa: BLE001 - status chrome must never stop the UI
                LOGGER.exception("event=system_status_refresh_failed")
            await asyncio.sleep(5.0)

    @staticmethod
    def _notify_watchdog() -> None:
        socket_path = os.environ.get("NOTIFY_SOCKET", "")
        if not socket_path or socket_path.startswith("@"):
            return
        import socket

        family = getattr(socket, "AF_UNIX", None)
        if family is None:  # pragma: no cover - Windows dev machines
            return
        with socket.socket(family, socket.SOCK_DGRAM) as sock:
            sock.connect(socket_path.replace("@", "\0", 1))
            sock.sendall(b"READY=1\nWATCHDOG=1")
