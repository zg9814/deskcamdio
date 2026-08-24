"""Fish aquarium home with the familiar pixel-art scene."""

from __future__ import annotations

import asyncio
import math
import time
from dataclasses import dataclass
from datetime import datetime

import pygame

from deskcamdio.core.lifecycle import App, LeaveReason, RouteState
from deskcamdio.core.runtime import RuntimeContext
from deskcamdio.ui import aquarium, components
from deskcamdio.ui.animation import FishAnimator
from deskcamdio.ui.themes import ThemeService, ThemeTokens
from deskcamdio.ui.typography import render_text

TAPS_TO_PLAY_DEAD = 8
TAP_WINDOW = 2.2
PLAY_DEAD_SECONDS = 5.0
VOICE_RECT = pygame.Rect(188, 342, 104, 68)
MUSIC_RECT = pygame.Rect(246, 22, 214, 76)
SUMMARY_RECTS = {
    "memo": pygame.Rect(62, 288, 116, 48),
    "gallery": pygame.Rect(182, 288, 116, 48),
    "pomodoro": pygame.Rect(302, 288, 116, 48),
}


@dataclass
class _MotionFish:
    x: float
    speed: float

    def update(self, delta: float) -> None:
        self.x = (self.x + self.speed * delta) % 480


class StandbyApp(App):
    def __init__(self) -> None:
        self._context: RuntimeContext | None = None
        self._main: FishAnimator | None = None
        self._companions: tuple[FishAnimator, ...] = ()
        self.elapsed = 0.0
        self._drag_start: tuple[int, int] | None = None
        self._fish_pressed = False
        self._tap_count = 0
        self._tap_remaining = 0.0
        self._playing_dead = 0.0
        self._reaction = 0.0
        self._summary = {"memos": 0, "photos": 0, "focus": 0}
        self._summary_remaining = 0.0
        self._summary_busy = False
        self.low_power = False
        self._fish = [_MotionFish(80.0, 24.0), _MotionFish(220.0, 18.0), _MotionFish(360.0, 30.0)]

    async def mount(self, context: RuntimeContext | None) -> None:
        self._context = context
        self._main = FishAnimator(0)
        self._companions = (FishAnimator(3), FishAnimator(7))
        if context is None:
            return
        self.low_power = bool(await context.store.get_setting("low_power_mode", False))
        unsubscribe = context.bus.subscribe("settings.changed", self._settings_changed)
        context.scope.track_subscription(unsubscribe, "standby settings")
        self._spawn_summary()

    async def enter(self, route: RouteState) -> None:
        del route
        self._spawn_summary()

    def _settings_changed(self, event: object) -> None:
        payload = getattr(event, "payload", {})
        if payload.get("key") == "low_power_mode":
            self.low_power = bool(payload.get("value", False))

    def _spawn_summary(self) -> None:
        if self._context is None or self._context.scope.closed or self._summary_busy:
            return
        self._summary_busy = True
        self._summary_remaining = 10.0
        self._context.scope.create_task(self._refresh_summary(), "summary")

    async def _refresh_summary(self) -> None:
        assert self._context is not None
        try:
            memos = await self._context.store.list_memos()
            pending = sum(not bool(item["completed"]) for item in memos)
            photos_dir = self._context.data_dir / "media" / "photos"
            photos = await asyncio.to_thread(
                lambda: sum(1 for p in photos_dir.glob("*.jpg")) if photos_dir.exists() else 0
            )
            row = await self._context.store.fetch_one(
                "SELECT completed_count FROM pomodoro_daily WHERE day=?",
                (time.strftime("%Y-%m-%d"),),
            )
            self._summary = {
                "memos": pending,
                "photos": photos,
                "focus": int(row[0]) if row else 0,
            }
        finally:
            self._summary_busy = False

    def _fish_position(self) -> tuple[int, int]:
        phase = self.elapsed * 0.52
        return 240 + round(math.sin(phase) * 46), 220 + round(math.sin(phase * 1.6) * 12)

    def _fish_hit(self, pos: tuple[int, int]) -> bool:
        x, y = self._fish_position()
        return pygame.Rect(x - 69, y - 58, 138, 116).collidepoint(pos)

    def handle_input(self, event: pygame.event.Event) -> None:  # noqa: C901
        context = self._context
        if context is None:
            return
        if event.type == pygame.MOUSEBUTTONDOWN and getattr(event, "button", 1) == 1:
            self._drag_start = event.pos
            self._fish_pressed = self._fish_hit(event.pos)
        elif event.type == pygame.MOUSEBUTTONUP and getattr(event, "button", 1) == 1:
            start = self._drag_start
            self._drag_start = None
            if start is not None and event.pos[0] - start[0] <= -60:
                if context.launch:
                    context.launch("launcher")
            elif VOICE_RECT.collidepoint(event.pos):
                context.bus.publish("voice.toggle")
            elif MUSIC_RECT.collidepoint(event.pos):
                if context.launch:
                    context.launch("music")
            else:
                for app_id, rect in SUMMARY_RECTS.items():
                    if rect.collidepoint(event.pos) and context.launch:
                        context.launch(app_id)
                        break
                else:
                    if self._fish_pressed and self._fish_hit(event.pos):
                        self._tap_fish()
                    elif context.launch:
                        context.launch("launcher")
            self._fish_pressed = False

    def _tap_fish(self) -> None:
        if self._main is None or self._playing_dead > 0:
            return
        self._tap_count = self._tap_count + 1 if self._tap_remaining > 0 else 1
        self._tap_remaining = TAP_WINDOW
        if self._tap_count >= TAPS_TO_PLAY_DEAD:
            self._tap_count = 0
            self._playing_dead = PLAY_DEAD_SECONDS
            self._main.set_clip("death", restart=True)
        else:
            self._reaction = 0.56
            self._main.set_clip("attack", restart=True)

    def update(self, delta_seconds: float) -> None:
        self.elapsed += delta_seconds
        if self._main is None:
            return
        self._main.update(delta_seconds)
        for fish in self._companions:
            fish.update(delta_seconds)
        for motion in self._fish:
            motion.update(delta_seconds)
        self._tap_remaining = max(0.0, self._tap_remaining - delta_seconds)
        if self._tap_remaining == 0:
            self._tap_count = 0
        if self._playing_dead > 0:
            self._playing_dead = max(0.0, self._playing_dead - delta_seconds)
            if self._playing_dead == 0:
                self._main.set_clip("swim", restart=True)
        elif self._reaction > 0:
            self._reaction = max(0.0, self._reaction - delta_seconds)
            if self._reaction == 0:
                self._main.set_clip("swim")
        self._summary_remaining -= delta_seconds
        if self._summary_remaining <= 0:
            self._spawn_summary()

    def render(self, surface: pygame.Surface) -> None:
        assert self._main is not None
        theme = self._context.theme.tokens if self._context else ThemeService().tokens
        if self.low_power:
            surface.fill((3, 12, 20))
            phase = self.elapsed * 0.32
            x = 240 + round(math.sin(phase) * 154)
            y = 240 + round(math.sin(phase * 1.7) * 20)
            image = self._main.frame((132, 132), flip_x=math.cos(phase) < 0)
            surface.blit(image, image.get_rect(center=(x, y)))
            return
        aquarium.ambient(surface, theme, self.elapsed)
        aquarium.seabed(surface, theme, self.elapsed)
        self._render_clock(surface, theme)
        self._render_music(surface, theme)
        self._render_fish(surface)
        self._render_summary(surface, theme)
        self._render_voice(surface, theme)
        components.page_dots(surface, 0, 3, theme, 450)

    @staticmethod
    def _render_clock(surface: pygame.Surface, theme: ThemeTokens) -> None:
        now = datetime.now()
        stamp = render_text(now.strftime("%H:%M"), 38, theme.text_primary, bold=True)
        surface.blit(stamp, (20, 16))
        weekdays = "一二三四五六日"
        date = render_text(
            f"{now.month}月{now.day}日  星期{weekdays[now.weekday()]}", 16, theme.text_secondary
        )
        surface.blit(date, (23, 63))

    def _render_music(self, surface: pygame.Surface, theme: ThemeTokens) -> None:
        components.glass_card(surface, MUSIC_RECT, theme, alpha=225, radius=20)
        components.icon(surface, "music", (271, 51), 24, theme.accent)
        media = self._context.audio.now_playing() if self._context else None
        title = str(media["title"]) if media else "暂无音乐"
        label = render_text(title[:14], 16, theme.text_primary, bold=True)
        surface.blit(label, (294, 33))
        state = render_text(
            "正在播放" if self._context and self._context.audio.music_playing else "本地曲库",
            13,
            theme.text_secondary,
        )
        surface.blit(state, (294, 59))

    def _render_fish(self, surface: pygame.Surface) -> None:
        assert self._main is not None
        phase = self.elapsed * 0.52
        for fish, (x, y, flip) in zip(
            self._companions, ((160, 142, False), (338, 268, True)), strict=True
        ):
            image = fish.frame((76, 76), flip_x=flip)
            surface.blit(image, image.get_rect(center=(x, y)))
        x, y = self._fish_position()
        image = self._main.frame((132, 132), flip_x=math.cos(phase) < 0)
        if self._playing_dead > 0:
            image = pygame.transform.flip(image, False, True)
            y = 220 + round((1 - self._playing_dead / PLAY_DEAD_SECONDS) * 62)
        surface.blit(image, image.get_rect(center=(x, y)))
        if self._reaction > 0:
            radius = round(35 + (1 - self._reaction / 0.56) * 45)
            color = self._context.theme.tokens.accent if self._context else (32, 118, 196)
            pygame.draw.circle(surface, color, (x, y), radius, 2)

    def _render_summary(self, surface: pygame.Surface, theme: ThemeTokens) -> None:
        values = (
            ("memo", "待办", self._summary["memos"]),
            ("gallery", "照片", self._summary["photos"]),
            ("pomodoro", "专注", self._summary["focus"]),
        )
        icons = {"memo": "notes", "gallery": "photo", "pomodoro": "clock"}
        for app_id, label, value in values:
            rect = SUMMARY_RECTS[app_id]
            components.glass_card(surface, rect, theme, alpha=232, radius=17)
            components.icon(surface, icons[app_id], (rect.x + 19, rect.centery), 16, theme.accent)
            text = render_text(f"{label} {value}", 14, theme.text_primary, bold=True)
            surface.blit(text, text.get_rect(midleft=(rect.x + 34, rect.centery)))

    @staticmethod
    def _render_voice(surface: pygame.Surface, theme: ThemeTokens) -> None:
        components.glass_card(surface, VOICE_RECT, theme, alpha=240, radius=25)
        components.icon(surface, "volume", (214, 370), 27, theme.accent)
        text = render_text("点击说话", 16, theme.text_primary, bold=True)
        surface.blit(text, (235, 360))

    async def leave(self, reason: LeaveReason) -> None:
        del reason

    async def dispose(self) -> None:
        if self._main:
            self._main.clear()
        for fish in self._companions:
            fish.clear()
        self._companions = ()
        self._fish.clear()
        self._context = None
        aquarium.clear_caches()
