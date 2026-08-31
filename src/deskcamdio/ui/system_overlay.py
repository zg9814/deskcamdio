"""Global status bar and Android-like pull-down quick controls."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import pygame

from deskcamdio.ui.typography import render_text


@dataclass(slots=True)
class SystemOverlay:
    width: int = 480
    height: int = 480
    status: dict[str, Any] = field(
        default_factory=lambda: {
            "wifi": False,
            "ssid": "",
            "bluetooth": False,
            "controller": False,
            "brightness": 80,
        }
    )
    volume: int = 80
    brightness: int = 80
    openness: float = 0.0
    _target: float = 0.0
    _pull_start: tuple[int, int] | None = None
    _pull_origin: float = 0.0
    _slider: str = ""

    @property
    def open(self) -> bool:
        return self._target >= 1.0 or self.openness >= 0.5

    @property
    def animating(self) -> bool:
        return abs(self._target - self.openness) > 0.005

    @property
    def interacting(self) -> bool:
        return self._pull_start is not None

    @property
    def active_slider(self) -> str:
        return self._slider

    def update(self, delta_seconds: float) -> None:
        # Frame-rate independent exponential settle; quick at first, soft at the end.
        blend = 1.0 - pow(0.0008, max(0.0, delta_seconds))
        self.openness += (self._target - self.openness) * blend
        if abs(self._target - self.openness) < 0.005:
            self.openness = self._target

    def handle_input(self, event: pygame.event.Event) -> tuple[str, int] | None:
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE and self.open:
            self._target = 0.0
            return ("consume", 0)
        if event.type == pygame.MOUSEBUTTONDOWN and getattr(event, "button", 1) == 1:
            return self._mouse_down((int(event.pos[0]), int(event.pos[1])))
        if event.type == pygame.MOUSEMOTION and self._pull_start is not None:
            return self._mouse_motion((int(event.pos[0]), int(event.pos[1])))
        if event.type == pygame.MOUSEBUTTONUP and self._pull_start is not None:
            return self._mouse_up((int(event.pos[0]), int(event.pos[1])))
        if self.open:
            return ("consume", 0)
        return None

    def _mouse_down(self, pos: tuple[int, int]) -> tuple[str, int] | None:
        if self.open:
            self._pull_start = pos
            self._pull_origin = self.openness
            slider = self._slider_at(pos)
            if slider:
                self._slider = slider
                return self._slider_value(slider, pos[0], commit=False)
            if pos[1] >= 414:
                self._target = 0.0
            return ("consume", 0)
        if pos[1] <= 34:
            self._pull_start = pos
            self._pull_origin = self.openness
            return ("consume", 0)
        return None

    def _mouse_motion(self, pos: tuple[int, int]) -> tuple[str, int]:
        if self._slider:
            return self._slider_value(self._slider, pos[0], commit=False)
        assert self._pull_start is not None
        distance = pos[1] - self._pull_start[1]
        self.openness = max(0.0, min(1.0, self._pull_origin + distance / 330.0))
        return ("consume", 0)

    def _mouse_up(self, pos: tuple[int, int]) -> tuple[str, int]:
        self._pull_start = None
        if self._slider:
            slider = self._slider
            self._slider = ""
            return self._slider_value(slider, pos[0], commit=True)
        self._target = 1.0 if self.openness >= 0.18 else 0.0
        return ("consume", 0)

    def _slider_at(self, pos: tuple[int, int]) -> str:
        if pygame.Rect(46, 157, 388, 52).collidepoint(pos):
            return "volume"
        if pygame.Rect(46, 251, 388, 52).collidepoint(pos):
            return "brightness"
        return ""

    def _slider_value(self, slider: str, x: int, *, commit: bool) -> tuple[str, int]:
        value = max(0, min(100, round((x - 62) * 100 / 356)))
        if slider == "brightness":
            value = max(5, value)
            self.brightness = value
        else:
            self.volume = value
        return (f"{slider}{'_commit' if commit else ''}", value)

    def render(self, surface: pygame.Surface, theme: Any) -> None:
        self._render_status_bar(surface, theme)
        if self.openness <= 0.0:
            return
        panel_height = int(424 * self.openness)
        panel = pygame.Surface((self.width, 424), pygame.SRCALPHA)
        panel.fill((*theme.background, 248))
        pygame.draw.rect(panel, theme.stroke, (0, 0, self.width, 424), width=1)
        title = render_text(time.strftime("%H:%M"), 36, theme.text_primary, bold=True)
        panel.blit(title, (28, 36))
        date = render_text(time.strftime("%Y-%m-%d"), 15, theme.text_secondary)
        panel.blit(date, (30, 82))

        chips = (
            ("Wi-Fi", bool(self.status.get("wifi")), str(self.status.get("ssid", ""))[:10]),
            ("蓝牙", bool(self.status.get("bluetooth")), "已开启"),
            ("手柄", bool(self.status.get("controller")), "已连接"),
        )
        for index, (label, active, detail) in enumerate(chips):
            rect = pygame.Rect(28 + index * 144, 112, 132, 54)
            color = theme.accent if active else theme.surface_elevated
            pygame.draw.rect(panel, color, rect, border_radius=18)
            text_color = (255, 255, 255) if active else theme.text_secondary
            text = render_text(label, 16, text_color, bold=True)
            panel.blit(text, (rect.x + 12, rect.y + 8))
            sub = render_text(detail if active else "未连接", 12, text_color)
            panel.blit(sub, (rect.x + 12, rect.y + 30))

        self._render_slider(panel, 190, "音量", self.volume, theme)
        self._render_slider(panel, 284, "亮度", self.brightness, theme)
        hint = render_text("向上滑动或点击底部收起", 14, theme.text_secondary)
        panel.blit(hint, hint.get_rect(center=(240, 395)))
        pygame.draw.rect(panel, theme.text_secondary, (210, 414, 60, 4), border_radius=2)
        surface.blit(panel, (0, panel_height - 424))

    @staticmethod
    def _render_slider(surface: pygame.Surface, y: int, label: str, value: int, theme: Any) -> None:
        text = render_text(f"{label}  {value}%", 17, theme.text_primary, bold=True)
        surface.blit(text, (46, y - 30))
        track = pygame.Rect(62, y, 356, 14)
        pygame.draw.rect(surface, theme.surface_elevated, track, border_radius=7)
        filled = max(14, round(track.width * value / 100))
        pygame.draw.rect(surface, theme.accent, (track.x, track.y, filled, 14), border_radius=7)
        pygame.draw.circle(
            surface, theme.accent, (track.x + round(track.width * value / 100), y + 7), 13
        )

    def _render_status_bar(self, surface: pygame.Surface, theme: Any) -> None:
        veil = pygame.Surface((self.width, 28), pygame.SRCALPHA)
        veil.fill((*theme.background, 145))
        surface.blit(veil, (0, 0))
        stamp = render_text(time.strftime("%H:%M"), 15, theme.text_primary, bold=True)
        surface.blit(stamp, stamp.get_rect(midtop=(240, 4)))
        x = self.width - 18
        x = self._status_symbol(
            surface, x, "controller", bool(self.status.get("controller")), theme
        )
        x = self._status_symbol(surface, x, "bluetooth", bool(self.status.get("bluetooth")), theme)
        self._status_symbol(surface, x, "wifi", bool(self.status.get("wifi")), theme)

    @staticmethod
    def _status_symbol(surface: pygame.Surface, x: int, kind: str, active: bool, theme: Any) -> int:
        color = theme.text_primary if active else theme.stroke
        if kind == "wifi":
            for radius in (4, 8, 12):
                pygame.draw.arc(
                    surface, color, (x - radius, 5, radius * 2, radius * 2), 0.75, 2.39, 2
                )
            pygame.draw.circle(surface, color, (x, 18), 2)
        elif kind == "bluetooth":
            pygame.draw.line(surface, color, (x, 5), (x, 21), 2)
            pygame.draw.lines(
                surface, color, False, ((x, 5), (x + 6, 10), (x - 5, 16), (x + 6, 21)), 2
            )
        else:
            pygame.draw.rect(surface, color, (x - 7, 9, 14, 9), width=2, border_radius=3)
            pygame.draw.circle(surface, color, (x - 4, 19), 2)
            pygame.draw.circle(surface, color, (x + 4, 19), 2)
        return x - 29


__all__ = ["SystemOverlay"]
