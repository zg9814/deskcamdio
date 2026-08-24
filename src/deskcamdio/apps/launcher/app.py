"""Two-page Fish launcher, visually continuous with the aquarium home."""

from __future__ import annotations

import pygame

from deskcamdio.core.lifecycle import App, LeaveReason, RouteState
from deskcamdio.core.runtime import RuntimeContext
from deskcamdio.ui import components, renderer
from deskcamdio.ui.themes import ThemeService
from deskcamdio.ui.typography import render_text

GRID = (("camera", "gallery", "music", "gba"), ("fishing", "memo", "pomodoro", "settings"))
ICONS = {
    "camera": "camera",
    "gallery": "photo",
    "music": "music",
    "gba": "player-play",
    "fishing": "fish",
    "memo": "notes",
    "pomodoro": "clock",
    "settings": "settings",
}
TILES = (
    pygame.Rect(32, 82, 196, 142),
    pygame.Rect(252, 82, 196, 142),
    pygame.Rect(32, 246, 196, 142),
    pygame.Rect(252, 246, 196, 142),
)


class LauncherApp(App):
    def __init__(self) -> None:
        self._context: RuntimeContext | None = None
        self.page = 0
        self._tiles: dict[str, pygame.Rect] = {}
        self._drag_start: tuple[int, int] | None = None
        self._drag_dx = 0.0

    async def mount(self, context: RuntimeContext | None) -> None:
        self._context = context

    async def enter(self, route: RouteState) -> None:
        self.page = max(0, min(1, int(route.args.get("page", self.page))))

    def _layout(self) -> None:
        self._tiles = dict(zip(GRID[self.page], TILES, strict=True))

    def handle_input(self, event: pygame.event.Event) -> None:
        if self._context is None:
            return
        if event.type == pygame.MOUSEBUTTONDOWN and getattr(event, "button", 1) == 1:
            self._drag_start = event.pos
            self._drag_dx = 0.0
        elif event.type == pygame.MOUSEMOTION and self._drag_start is not None:
            self._drag_dx = event.pos[0] - self._drag_start[0]
        elif event.type == pygame.MOUSEBUTTONUP and getattr(event, "button", 1) == 1:
            if self._drag_start is None:
                return
            if self._drag_dx <= -60 and self.page == 0:
                self.page = 1
            elif self._drag_dx >= 60 and self.page == 1:
                self.page = 0
            elif self._drag_dx >= 60 and self.page == 0:
                self._context.launch("standby") if self._context.launch else None
            else:
                hit = components.hit_test(self._tiles, event.pos)
                if hit and self._context.launch:
                    self._context.launch(hit)
            self._drag_start = None

    def update(self, delta_seconds: float) -> None:
        del delta_seconds

    def render(self, surface: pygame.Surface) -> None:
        theme = self._context.theme.tokens if self._context else ThemeService().tokens
        renderer.background(surface, theme)
        title = render_text("Fish 应用", 24, theme.text_primary, bold=True)
        surface.blit(title, (22, 22))
        hint = render_text(
            "右滑返回水族首页" if self.page == 0 else "第二页", 14, theme.text_secondary
        )
        surface.blit(hint, (surface.get_width() - hint.get_width() - 22, 28))
        self._layout()
        names = {d.app_id: d.name for d in self._context.app_catalog} if self._context else {}
        for app_id, rect in self._tiles.items():
            components.glass_card(surface, rect, theme, alpha=235, radius=26)
            components.icon(surface, ICONS[app_id], (rect.centerx, rect.y + 48), 46, theme.accent)
            label = render_text(names.get(app_id, app_id), 18, theme.text_primary, bold=True)
            surface.blit(label, label.get_rect(midtop=(rect.centerx, rect.y + 86)))
        components.page_dots(surface, self.page + 1, 3, theme, 442)

    async def leave(self, reason: LeaveReason) -> None:
        del reason
        self._tiles.clear()

    async def dispose(self) -> None:
        self._context = None
