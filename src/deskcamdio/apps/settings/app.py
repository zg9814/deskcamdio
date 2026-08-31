"""Settings: theme, volume, brightness, device info, data management."""

from __future__ import annotations

import asyncio
import os
import platform as _platform
from pathlib import Path
from typing import Any

import pygame

from deskcamdio.core.lifecycle import App, LeaveReason, RouteState
from deskcamdio.core.runtime import RuntimeContext
from deskcamdio.ui import components, renderer
from deskcamdio.ui.themes import DEFAULT_THEME_ID, THEMES, ThemeTokens
from deskcamdio.ui.typography import render_text

TABS = ["外观", "声音", "设备", "数据"]
DEVICE_REFRESH_INTERVAL_S = 5.0

_DEVICE_DEFAULTS: dict[str, Any] = {
    "wifi": {"connected": False, "ssid": ""},
    "bt": {"powered": False},
    "brightness": 0,
}


def _collect_device_snapshot(system: Any) -> dict[str, Any]:
    """Blocking probes run off the UI thread; each probe degrades alone."""

    def safe(fn: Any, default: Any) -> Any:
        try:
            return fn()
        except Exception:  # noqa: BLE001 - a missing tool must not blank the page
            return default

    return {
        "wifi": safe(system.wifi_status, dict(_DEVICE_DEFAULTS["wifi"])),
        "bt": safe(system.bluetooth_status, dict(_DEVICE_DEFAULTS["bt"])),
        "brightness": safe(system.get_brightness, _DEVICE_DEFAULTS["brightness"]),
    }


def _collect_diagnostics(run_dir: Path) -> dict[str, Any]:
    from deskcamdio.core.health import sample_process, sample_system
    from deskcamdio.services.touch_relay import discover_touch_device

    controllers = 0
    try:
        import evdev

        for path in evdev.list_devices():
            device = evdev.InputDevice(path)
            try:
                name = device.name.lower()
                controllers += int(
                    any(tag in name for tag in ("gamepad", "controller", "joystick"))
                )
            finally:
                device.close()
    except (ImportError, OSError):
        pass
    return {
        **sample_process(),
        **sample_system(),
        "touch": discover_touch_device() is not None,
        "gpio": os.getenv("DESKCAMDIO_PLATFORM") == "raspberry_pi",
        "camera_worker": (run_dir / "camera-worker.pid").exists(),
        "controllers": controllers,
    }


class SettingsApp(App):
    def __init__(self) -> None:
        self._context: RuntimeContext | None = None
        self.page = 0
        self.volume = 80
        self.brightness = 100
        self.theme_id = DEFAULT_THEME_ID
        self.screen_timeout = 0
        self._tabs: dict[str, pygame.Rect] = {}
        self._swatches: dict[str, pygame.Rect] = {}
        self._device_buttons: dict[str, pygame.Rect] = {}
        # nmcli/bluetoothctl take hundreds of ms — never probe them from the
        # render path. render() reads this snapshot; refreshes are scheduled.
        self.device_snapshot: dict[str, Any] = dict(_DEVICE_DEFAULTS)
        self._device_refreshing = False
        self._device_refreshed_at = float("-inf")
        self._device_busy = ""
        self._bt_candidates: list[dict[str, Any]] = []
        self._wifi_candidates: list[dict[str, Any]] = []
        self._wifi_mode = ""
        self._wifi_selected: dict[str, Any] | None = None
        self._wifi_password = ""
        self._wifi_uppercase = False
        self._wifi_symbols = False
        self._wifi_buttons: dict[str, pygame.Rect] = {}

    def _spawn(self, coro: Any, *, name: str | None = None) -> Any:
        """Schedule work on this app's TaskScope; returns the Task."""
        import asyncio

        ctx = self._context
        scope = getattr(ctx, "scope", None) if ctx is not None else None
        if scope is not None:
            return scope.create_task(coro, name=name)
        return asyncio.get_running_loop().create_task(coro, name=name)

    async def mount(self, context: RuntimeContext) -> None:
        self._context = context
        stored_theme = await context.store.get_setting("theme", DEFAULT_THEME_ID)
        if stored_theme in THEMES:
            self.theme_id = str(stored_theme)
        self.volume = int(await context.store.get_setting("volume", 80))
        self.brightness = int(await context.store.get_setting("brightness", 100))
        self.screen_timeout = int(await context.store.get_setting("screen_timeout_seconds", 0))
        context.theme.select(self.theme_id)

    def _schedule_device_refresh(self, *, force: bool = False) -> None:
        """Probe Wi-Fi/BT/brightness off-thread; throttled unless forced."""
        import asyncio
        import time as _time

        context = self._context
        if context is None:
            return
        system = context.system
        if system is None or self._device_refreshing:
            return
        now = _time.monotonic()
        if not force and now - self._device_refreshed_at < DEVICE_REFRESH_INTERVAL_S:
            return

        async def _refresh() -> None:
            try:
                self.device_snapshot = await asyncio.to_thread(_collect_device_snapshot, system)
                diagnostics = await asyncio.to_thread(
                    _collect_diagnostics, context.effective_run_dir
                )
                diagnostics["audio"] = bool(pygame.mixer.get_init()) or bool(os.getenv("AUDIODEV"))
                self.device_snapshot["diagnostics"] = diagnostics
                self._device_refreshed_at = _time.monotonic()
            finally:
                self._device_refreshing = False

        # Claim the slot synchronously: consecutive render() calls run without
        # awaits, so an in-coroutine flag would let tasks pile up.
        self._device_refreshing = True
        self._spawn(_refresh(), name="settings-device-snapshot")

    async def enter(self, route: RouteState) -> None:
        self._schedule_device_refresh(force=True)

    def handle_input(self, event: pygame.event.Event) -> None:
        context = self._context
        if context is None:
            return
        if self._wifi_mode:
            self._handle_wifi_input(event, context)
            return
        if event.type != pygame.MOUSEBUTTONDOWN:
            return
        self._handle_settings_click(event.pos, context)

    def _handle_wifi_input(self, event: pygame.event.Event, context: RuntimeContext) -> None:
        if event.type == pygame.KEYDOWN:
            self._wifi_key_input(event, context)
        elif event.type == pygame.MOUSEBUTTONDOWN:
            self._wifi_modal_click(event.pos, context)

    def _handle_settings_click(self, pos: tuple[int, int], context: RuntimeContext) -> None:
        for name, rect in self._tabs.items():
            if rect.collidepoint(pos):
                self.page = TABS.index(name)
                return
        if self.page == 0:
            for theme_id, rect in self._swatches.items():
                if rect.collidepoint(pos):
                    self.theme_id = theme_id
                    context.theme.select(theme_id)

                    self._spawn(context.store.set_setting("theme", theme_id))
                    return
        elif self.page == 1:
            self._sound_click(pos, context)
        elif self.page == 2:
            self._device_click(pos, context)

    def _sound_click(self, pos: tuple[int, int], context: RuntimeContext) -> None:
        if not self._volume_track.collidepoint(pos):
            return
        ratio = (pos[0] - self._volume_track.x) / self._volume_track.width
        self.volume = max(0, min(100, round(ratio * 100)))
        self.audio_volume_sync = True

        self._spawn(context.store.set_setting("volume", self.volume))
        context.audio.set_volume(self.volume)
        system = getattr(context, "system", None)
        if system is not None and hasattr(system, "set_system_volume"):
            self._spawn(asyncio.to_thread(system.set_system_volume, self.volume), name="volume")

    def _device_click(self, pos: tuple[int, int], context: RuntimeContext) -> None:
        system = getattr(context, "system", None)
        hit_key = next(
            (key for key, rect in self._device_buttons.items() if rect.collidepoint(pos)),
            None,
        )
        if hit_key is None:
            return
        if hit_key.startswith("timeout:"):
            seconds = int(hit_key.split(":")[1])
            self.screen_timeout = seconds
            self._spawn(context.store.set_setting("screen_timeout_seconds", seconds))
            self.show_toast_local(f"息屏 {seconds} 秒")
        elif system is not None and not self._device_busy:
            self._device_busy = hit_key
            self._spawn(self._run_device_action(hit_key, system, context), name=hit_key)

    def _wifi_modal_click(self, pos: tuple[int, int], context: RuntimeContext) -> None:
        hit = next((key for key, rect in self._wifi_buttons.items() if rect.collidepoint(pos)), "")
        if hit == "cancel":
            self._wifi_mode = ""
            self._wifi_password = ""
        elif hit == "rescan" and not self._device_busy:
            self._device_busy = "wifi_scan"
            self._spawn(self._run_device_action("wifi_scan", context.system, context))
        elif hit.startswith("network:"):
            index = int(hit.split(":", 1)[1])
            if index >= len(self._wifi_candidates):
                return
            self._wifi_selected = self._wifi_candidates[index]
            if str(self._wifi_selected.get("security", "")):
                self._wifi_mode = "password"
                self._wifi_password = ""
            else:
                self._start_wifi_connect(context)
        else:
            self._edit_wifi_password(hit, context)

    def _edit_wifi_password(self, hit: str, context: RuntimeContext) -> None:
        if hit == "backspace":
            self._wifi_password = self._wifi_password[:-1]
        elif hit == "case":
            self._wifi_uppercase = not self._wifi_uppercase
            self._wifi_symbols = False
        elif hit == "symbols":
            self._wifi_symbols = not self._wifi_symbols
        elif hit == "space" and len(self._wifi_password) < 63:
            self._wifi_password += " "
        elif hit == "connect":
            self._start_wifi_connect(context)
        elif hit.startswith("key:") and len(self._wifi_password) < 63:
            self._wifi_password += hit.split(":", 1)[1]

    def _wifi_key_input(self, event: pygame.event.Event, context: RuntimeContext) -> None:
        if event.key == pygame.K_ESCAPE:
            self._wifi_mode = ""
        elif event.key == pygame.K_BACKSPACE:
            self._wifi_password = self._wifi_password[:-1]
        elif event.key in {pygame.K_RETURN, pygame.K_KP_ENTER}:
            self._start_wifi_connect(context)
        elif event.unicode and event.unicode.isprintable() and len(self._wifi_password) < 63:
            self._wifi_password += event.unicode

    def _start_wifi_connect(self, context: RuntimeContext) -> None:
        if self._wifi_selected is None or self._device_busy:
            return
        self._device_busy = "wifi_connect"
        self._spawn(self._run_device_action("wifi_connect", context.system, context))

    async def _run_device_action(self, key: str, system: Any, context: RuntimeContext) -> None:
        try:
            if key.startswith("wifi_"):
                await self._run_wifi_action(key, system)
            elif key == "bt_toggle":
                powered = await asyncio.to_thread(system.bluetooth_toggle)
                self.show_toast_local("蓝牙已开" if powered else "蓝牙已关")
            elif key == "bt_scan":
                self.show_toast_local("正在扫描蓝牙手柄…")
                self._bt_candidates = await asyncio.to_thread(system.bluetooth_scan_controllers)
                self.show_toast_local(
                    f"发现 {len(self._bt_candidates)} 个设备"
                    if self._bt_candidates
                    else "未发现手柄，请先开启配对模式"
                )
            elif key.startswith("bt_connect:"):
                address = key.split(":", 1)[1]
                connected = await asyncio.to_thread(system.bluetooth_connect_controller, address)
                self.show_toast_local("手柄已连接" if connected else "手柄连接失败")
                if connected:
                    for candidate in self._bt_candidates:
                        if candidate.get("address") == address:
                            candidate["connected"] = True
            elif key in {"brightness_up", "brightness_down"}:
                current = await asyncio.to_thread(system.get_brightness)
                target = max(5, min(100, current + (10 if key.endswith("up") else -10)))
                if await asyncio.to_thread(system.set_brightness, target):
                    self.brightness = target
                    await context.store.set_setting("brightness", target)
            self._schedule_device_refresh(force=True)
        finally:
            self._device_busy = ""

    async def _run_wifi_action(self, key: str, system: Any) -> None:
        if key == "wifi_reconnect":
            ok = await asyncio.to_thread(system.wifi_reconnect)
            self.show_toast_local("Wi-Fi 已重连" if ok else "重连失败")
        elif key == "wifi_scan":
            self.show_toast_local("正在扫描 Wi-Fi…")
            self._wifi_candidates = await asyncio.to_thread(system.wifi_scan)
            self._wifi_mode = "networks"
            self.show_toast_local(
                f"发现 {len(self._wifi_candidates)} 个网络"
                if self._wifi_candidates
                else "没有发现 Wi-Fi"
            )
        elif key == "wifi_connect":
            selected = self._wifi_selected or {}
            ssid = str(selected.get("ssid", ""))
            password = self._wifi_password
            ok = await asyncio.to_thread(system.wifi_connect, ssid, password)
            self._wifi_password = ""
            if ok:
                self._wifi_mode = ""
                self.show_toast_local(f"已连接 {ssid}")
            else:
                self.show_toast_local("连接失败，请检查密码")

    _toast_text = ""
    _toast_until = 0.0

    def show_toast_local(self, text: str) -> None:
        """Local toast fallback when the runtime helper isn't wired here."""
        import time as _time

        self._toast_text = text
        self._toast_until = _time.monotonic() + 2.5

    def update(self, delta_seconds: float) -> None:
        del delta_seconds
        if self.page == 2:
            self._schedule_device_refresh()

    _volume_track = pygame.Rect(60, 200, 360, 14)

    def render(self, surface: pygame.Surface) -> None:
        assert self._context is not None
        theme = self._context.theme.tokens
        renderer.background(surface, theme)
        if self._wifi_mode:
            self._render_wifi_modal(surface, theme)
            return
        title = render_text("设置", 20, theme.text_primary, bold=True)
        surface.blit(title, (16, 12))

        self._tabs.clear()
        for index, name in enumerate(TABS):
            rect = pygame.Rect(16 + index * 116, 40, 108, 48)
            selected = index == self.page
            pygame.draw.rect(
                surface, theme.accent if selected else theme.surface, rect, border_radius=12
            )
            text = render_text(name, 17, (255, 255, 255) if selected else theme.text_primary)
            surface.blit(text, text.get_rect(center=rect.center))
            self._tabs[name] = rect

        if self.page == 0:
            self._render_appearance(surface, theme)
        elif self.page == 1:
            self._render_sound(surface, theme)
        elif self.page == 2:
            self._render_device(surface, theme)
        else:
            self._render_data(surface, theme)

    def _render_appearance(self, surface: pygame.Surface, theme: ThemeTokens) -> None:
        label = render_text("主题（立即生效并保存）", 16, theme.text_secondary)
        surface.blit(label, (20, 104))
        self._swatches.clear()
        for index, (theme_id, tokens) in enumerate(THEMES.items()):
            row_rect = pygame.Rect(20, 132 + index * 62, 440, 54)
            selected = theme_id == self.theme_id
            pygame.draw.rect(surface, theme.surface, row_rect, border_radius=14)
            if selected:
                pygame.draw.rect(surface, theme.accent, row_rect, width=2, border_radius=14)
            preview = pygame.Rect(row_rect.x + 10, row_rect.y + 9, 72, 36)
            pygame.draw.rect(surface, tokens.background, preview, border_radius=8)
            pygame.draw.circle(surface, tokens.accent, (preview.right - 14, preview.centery), 8)
            name_text = render_text(tokens.name, 18, theme.text_primary)
            surface.blit(name_text, (row_rect.x + 96, row_rect.y + 15))
            self._swatches[theme_id] = row_rect

    def _render_sound(self, surface: pygame.Surface, theme: ThemeTokens) -> None:
        vol_label = render_text(f"音量 {self.volume}", 18, theme.text_primary)
        surface.blit(vol_label, (20, 160))
        track = self._volume_track
        pygame.draw.rect(surface, theme.surface_elevated, track, border_radius=7)
        knob_x = track.x + int(track.width * self.volume / 100)
        pygame.draw.rect(
            surface,
            theme.accent,
            (track.x, track.y, max(14, knob_x - track.x), track.height),
            border_radius=7,
        )
        pygame.draw.circle(surface, theme.accent, (knob_x, track.centery), 11)

    def _render_device(self, surface: pygame.Surface, theme: ThemeTokens) -> None:
        self._schedule_device_refresh()
        info_lines = [
            f"系统：{_platform.system()} {_platform.machine()}",
            f"Python：{_platform.python_version()}",
        ]
        for index, line in enumerate(info_lines):
            surface.blit(render_text(line, 15, theme.text_secondary), (20, 96 + index * 26))

        wifi = dict(_DEVICE_DEFAULTS["wifi"])
        wifi.update(self.device_snapshot.get("wifi", {}))
        bt = dict(_DEVICE_DEFAULTS["bt"])
        bt.update(self.device_snapshot.get("bt", {}))
        brightness = int(self.device_snapshot.get("brightness", 0))

        self._device_buttons.clear()
        wifi_text = "已连接 " + str(wifi.get("ssid", "")) if wifi.get("connected") else "未连接"
        components.row(surface, pygame.Rect(20, 146, 440, 48), f"Wi-Fi：{wifi_text}", theme)
        self._device_buttons["wifi_scan"] = pygame.Rect(330, 146, 126, 48)
        components.ghost_button(surface, self._device_buttons["wifi_scan"], "配置", theme, size=14)

        bt_label = "蓝牙：开" if bt.get("powered") else "蓝牙：关"
        components.row(surface, pygame.Rect(20, 200, 440, 48), bt_label, theme)
        self._device_buttons["bt_toggle"] = pygame.Rect(330, 200, 126, 48)
        components.ghost_button(
            surface, self._device_buttons["bt_toggle"], "切换电源", theme, size=14
        )

        candidate = self._bt_candidates[0] if self._bt_candidates else None
        controller_text = (
            f"手柄：{str(candidate.get('name', '设备'))[:14]}"
            if candidate is not None
            else "手柄：等待扫描"
        )
        components.row(
            surface,
            pygame.Rect(20, 254, 440, 48),
            controller_text,
            theme,
            trailing=" ",
        )
        if candidate is not None and not candidate.get("connected"):
            controller_key = f"bt_connect:{candidate.get('address', '')}"
            controller_label = "配对连接"
        elif candidate is not None:
            controller_key = "bt_scan"
            controller_label = "已连接"
        else:
            controller_key = "bt_scan"
            controller_label = "扫描手柄"
        self._device_buttons[controller_key] = pygame.Rect(330, 254, 126, 48)
        components.ghost_button(
            surface,
            self._device_buttons[controller_key],
            controller_label,
            theme,
            size=14,
        )

        components.row(surface, pygame.Rect(20, 308, 440, 48), f"亮度 {brightness}%", theme)
        for key, label, rect in (
            ("brightness_down", "－", pygame.Rect(300, 308, 66, 48)),
            ("brightness_up", "＋", pygame.Rect(376, 308, 66, 48)),
        ):
            self._device_buttons[key] = rect
            components.ghost_button(surface, rect, label, theme)

        current_timeout = self.screen_timeout
        timeout_label = "息屏：关" if current_timeout == 0 else f"息屏：{current_timeout}s"
        components.row(surface, pygame.Rect(20, 362, 440, 48), timeout_label, theme)
        for index, seconds in enumerate((30, 60, 300)):
            rect = pygame.Rect(280 + index * 64, 362, 60, 48)
            self._device_buttons[f"timeout:{seconds}"] = rect
            selected = current_timeout == seconds
            pygame.draw.rect(
                surface,
                theme.surface_elevated if selected else theme.surface,
                rect,
                border_radius=8,
            )
            text = render_text(f"{seconds}", 14, theme.text_primary)
            surface.blit(text, text.get_rect(center=rect.center))

    def _render_data(self, surface: pygame.Surface, theme: ThemeTokens) -> None:
        note = render_text("数据目录：state.db / media / music / roms", 15, theme.text_secondary)
        surface.blit(note, (20, 120))
        diagnostics = self.device_snapshot.get("diagnostics", {})
        available = int(diagnostics.get("available_memory_kb", 0)) // 1024
        rows = (
            (
                "输入",
                f"触控 {'就绪' if diagnostics.get('touch') else '未发现'} · "
                f"GPIO {'就绪' if diagnostics.get('gpio') else '模拟'}",
            ),
            (
                "媒体",
                f"音频 {'就绪' if diagnostics.get('audio') else '静默'} · "
                f"相机 {'运行中' if diagnostics.get('camera_worker') else '按需启动'}",
            ),
            ("手柄", f"已连接 {int(diagnostics.get('controllers', 0))} 个"),
            ("内存", f"可用 {available} MB · RSS {int(diagnostics.get('rss_kb', 0)) // 1024} MB"),
        )
        for index, (label, value) in enumerate(rows):
            components.row(
                surface,
                pygame.Rect(20, 158 + index * 58, 440, 50),
                label,
                theme,
                trailing=value,
                size=17,
            )

    def _render_wifi_modal(self, surface: pygame.Surface, theme: ThemeTokens) -> None:
        self._wifi_buttons.clear()
        title = "选择 Wi-Fi" if self._wifi_mode == "networks" else "输入 Wi-Fi 密码"
        surface.blit(render_text(title, 22, theme.text_primary, bold=True), (22, 38))
        cancel = pygame.Rect(374, 30, 84, 48)
        self._wifi_buttons["cancel"] = cancel
        components.ghost_button(surface, cancel, "取消", theme, size=15)
        if self._wifi_mode == "networks":
            for index, network in enumerate(self._wifi_candidates[:6]):
                rect = pygame.Rect(20, 88 + index * 54, 440, 48)
                ssid = str(network.get("ssid", ""))[:24]
                security = "加密" if network.get("security") else "开放"
                trailing = f"{int(network.get('signal', 0))}% · {security}"
                components.row(surface, rect, ssid, theme, trailing=trailing, size=17)
                self._wifi_buttons[f"network:{index}"] = rect
            rescan = pygame.Rect(160, 420, 160, 48)
            self._wifi_buttons["rescan"] = rescan
            components.ghost_button(surface, rescan, "重新扫描", theme, size=16)
            return

        ssid = str((self._wifi_selected or {}).get("ssid", ""))
        surface.blit(render_text(ssid[:28], 16, theme.text_secondary), (24, 82))
        password_box = pygame.Rect(22, 108, 436, 48)
        pygame.draw.rect(surface, theme.surface_elevated, password_box, border_radius=12)
        masked = "•" * min(24, len(self._wifi_password))
        surface.blit(render_text(masked or "至少 8 位密码", 17, theme.text_primary), (38, 122))

        rows = (
            ("!@#$%^&*()", "_-+=[]{}", ";:'\",.<>", "?/\\|~`")
            if self._wifi_symbols
            else ("1234567890", "qwertyuiop", "asdfghjkl", "zxcvbnm")
        )
        for row_index, raw_row in enumerate(rows):
            row = raw_row.upper() if self._wifi_uppercase else raw_row
            key_width = 40 if len(row) >= 10 else 44
            total = len(row) * key_width
            start_x = (480 - total) // 2
            y = 172 + row_index * 52
            for column, char in enumerate(row):
                rect = pygame.Rect(start_x + column * key_width + 2, y, key_width - 4, 46)
                self._wifi_buttons[f"key:{char}"] = rect
                components.ghost_button(surface, rect, char, theme, size=15)
        controls = (
            ("case", "Aa", pygame.Rect(12, 382, 58, 48)),
            ("symbols", "符号", pygame.Rect(76, 382, 78, 48)),
            ("backspace", "删除", pygame.Rect(160, 382, 76, 48)),
            ("space", "空格", pygame.Rect(242, 382, 76, 48)),
            ("connect", "连接", pygame.Rect(330, 382, 128, 48)),
        )
        for key, label, rect in controls:
            self._wifi_buttons[key] = rect
            components.ghost_button(surface, rect, label, theme, size=16)

    async def leave(self, reason: LeaveReason) -> None:
        del reason

    async def dispose(self) -> None:
        self._context = None
        self._tabs.clear()
        self._swatches.clear()
