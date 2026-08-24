"""Pomodoro: TimerService-backed countdown persisted in StateStore."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import pygame

from deskcamdio.core.lifecycle import App, LeaveReason, RouteState
from deskcamdio.core.runtime import RuntimeContext
from deskcamdio.ui import components
from deskcamdio.ui.aquarium import gradient
from deskcamdio.ui.typography import render_text

MIN_MINUTES = 5
MAX_MINUTES = 120


class PomodoroApp(App):
    def __init__(self) -> None:
        self._context: RuntimeContext | None = None
        self._unsub_configure: Callable[[], None] | None = None
        self.duration = 25 * 60
        self.remaining: float = 25 * 60
        self.running = False
        self.today_done = 0
        self._last_tick = 0.0
        self._buttons: dict[str, pygame.Rect] = {}
        self._loaded = False

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

        def on_configure(event: Any) -> None:
            minutes = int(event.payload.get("minutes", 25))
            self.duration = max(MIN_MINUTES, min(MAX_MINUTES, minutes)) * 60
            self.remaining = self.duration
            self.running = False

            self._spawn(self._persist())

        self._unsub_configure = context.bus.subscribe("pomodoro.configure", on_configure)
        if getattr(context, "scope", None) is not None:
            context.scope.track_subscription(self._unsub_configure, name="pomodoro:configure")  # noqa: E501

    async def _load(self) -> None:
        context = self._context
        assert context is not None
        row = await context.store.fetch_one(
            "SELECT duration_seconds, remaining_seconds, running FROM pomodoro_state WHERE id=1"
        )
        if row is not None and not self._loaded:
            self.duration, self.remaining, running = row
            self.running = bool(running)
            self._loaded = True
        day = time.strftime("%Y-%m-%d")
        count = await context.store.fetch_one(
            "SELECT completed_count FROM pomodoro_daily WHERE day=?", (day,)
        )
        self.today_done = int(count[0]) if count else 0

    async def enter(self, route: RouteState) -> None:
        await self._load()

    async def _persist(self) -> None:
        context = self._context
        assert context is not None
        await context.store.save_pomodoro(self.duration, self.remaining, self.running)

    def handle_input(self, event: pygame.event.Event) -> None:
        context = self._context
        if context is None or event.type != pygame.MOUSEBUTTONDOWN:
            return
        for key, rect in self._buttons.items():
            if not rect.collidepoint(event.pos):
                continue
            if key == "start":
                self.running = True
                self.remaining = self.remaining or self.duration
            elif key == "pause":
                self.running = False
            elif key == "reset":
                self.running = False
                self.remaining = self.duration
            elif key == "plus":
                self.duration = min(MAX_MINUTES * 60, self.duration + 60)
                self.remaining = self.duration
                self.running = False
            elif key == "minus":
                self.duration = max(MIN_MINUTES * 60, self.duration - 60)
                self.remaining = self.duration
                self.running = False

            self._spawn(self._persist())
            break

    def update(self, delta_seconds: float) -> None:
        if not self.running:
            return
        now = time.monotonic()
        if self._last_tick == 0.0:
            self._last_tick = now
        elapsed = now - self._last_tick
        self._last_tick = now
        self.remaining -= elapsed
        if self.remaining <= 0:
            self.remaining = 0.0
            self.running = False
            self.today_done += 1
            context = self._context
            if context is not None:
                context.audio.play_sound("alarm", category="alarm")
                day = time.strftime("%Y-%m-%d")

                self._spawn(context.store.bump_pomodoro_daily(day))
                self._spawn(self._persist())

    def render(self, surface: pygame.Surface) -> None:
        assert self._context is not None
        theme = self._context.theme.tokens
        gradient(surface, theme)
        minutes, seconds = divmod(max(0, int(self.remaining)), 60)
        clock_text = render_text(f"{minutes:02d}:{seconds:02d}", 72, theme.text_primary, bold=True)
        surface.blit(clock_text, clock_text.get_rect(center=(240, 150)))

        components.progress_bar(
            surface, pygame.Rect(80, 220, 320, 10), self.remaining / max(1, self.duration), theme
        )
        today = render_text(f"今日完成 {self.today_done} 个番茄", 16, theme.text_secondary)
        surface.blit(today, today.get_rect(center=(240, 260)))

        self._buttons = {
            "minus": pygame.Rect(60, 298, 90, 48),
            "plus": pygame.Rect(330, 298, 90, 48),
            "start": pygame.Rect(160, 356, 76, 48),
            "pause": pygame.Rect(244, 356, 76, 48),
            "reset": pygame.Rect(202, 410, 76, 48),
        }
        components.ghost_button(surface, self._buttons["minus"], "-1分", theme)
        components.ghost_button(surface, self._buttons["plus"], "+1分", theme)
        components.button(surface, self._buttons["start"], "开始", theme, pressed=self.running)
        components.button(surface, self._buttons["pause"], "暂停", theme)
        components.ghost_button(surface, self._buttons["reset"], "重置", theme)
        length = render_text(f"时长 {self.duration // 60} 分钟", 15, theme.text_secondary)
        surface.blit(length, length.get_rect(center=(240, 322)))

    async def leave(self, reason: LeaveReason) -> None:
        # Timer keeps running in background state; persist latest values.
        del reason

    async def dispose(self) -> None:
        if self._unsub_configure is not None:
            self._unsub_configure()
            self._unsub_configure = None
        self._context = None
        self._buttons.clear()
