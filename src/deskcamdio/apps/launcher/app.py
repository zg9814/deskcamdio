"""Two-page Fish launcher, visually continuous with the aquarium home."""

from __future__ import annotations

import pygame

from deskcamdio.core.lifecycle import App, LeaveReason, RouteState
from deskcamdio.core.runtime import RuntimeContext
from deskcamdio.ui import components, renderer
from deskcamdio.ui.pager import PagePager
from deskcamdio.ui.themes import ThemeService
from deskcamdio.ui.typography import render_text

GRID = (
    ("camera", "gallery", "music", "gba"),
    ("fishing", "memo", "pomodoro", "settings"),
    ("ps1",),
)
ICONS = {
    "camera": "camera",
    "gallery": "photo",
    "music": "music",
    "gba": "player-play",
    "ps1": "player-play",
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
        self.pager = PagePager(len(GRID))
        self._tiles: dict[str, pygame.Rect] = {}
        self._drag_start: tuple[int, int] | None = None
        self._page_surface = pygame.Surface((480, 480))

    @property
    def page(self) -> int:
        return self.pager.index

    @page.setter
    def page(self, value: int) -> None:
        self.pager.set_index(value)

    @property
    def preferred_fps(self) -> int:
        return 60 if self.pager.is_animating or self.pager.is_dragging else 0

    async def mount(self, context: RuntimeContext | None) -> None:
        self._context = context

    async def enter(self, route: RouteState) -> None:
        self.pager.set_index(int(route.args.get("page", self.page)))

    def _layout(self, page: int | None = None) -> dict[str, pygame.Rect]:
        return dict(zip(GRID[self.page if page is None else page], TILES, strict=False))

    def handle_input(self, event: pygame.event.Event) -> None:
        if self._context is None:
            return
        if event.type == pygame.MOUSEBUTTONDOWN and getattr(event, "button", 1) == 1:
            self._drag_start = event.pos
            self.pager.begin_drag(event.pos[0])
        elif event.type == pygame.MOUSEMOTION and self._drag_start is not None:
            self.pager.drag_to(event.pos[0])
        elif event.type == pygame.MOUSEBUTTONUP and getattr(event, "button", 1) == 1:
            if self._drag_start is None:
                return
            drag_dx = event.pos[0] - self._drag_start[0]
            dragged = self.pager.end_drag(event.pos[0])
            if drag_dx >= 60 and self.page == 0:
                self.pager.set_index(0)
                self._context.launch("standby") if self._context.launch else None
            elif not dragged:
                self._tiles = self._layout()
                hit = components.hit_test(self._tiles, event.pos)
                if hit and self._context.launch:
                    self._context.launch(hit)
            self._drag_start = None

    def update(self, delta_seconds: float) -> None:
        self.pager.update(delta_seconds)

    def render(self, surface: pygame.Surface) -> None:
        for page in self.pager.visible_pages():
            self._page_surface.fill((0, 0, 0))
            self._render_page(self._page_surface, page)
            surface.blit(self._page_surface, (self.pager.page_x(page), 0))
        self._tiles = self._layout()

    def _render_page(self, surface: pygame.Surface, page: int) -> None:
        theme = self._context.theme.tokens if self._context else ThemeService().tokens
        renderer.background(surface, theme)
        title = render_text("Fish 应用", 24, theme.text_primary, bold=True)
        surface.blit(title, (22, 22))
        hint = render_text(
            "右滑返回水族首页" if page == 0 else f"第 {page + 1} 页",
            14,
            theme.text_secondary,
        )
        surface.blit(hint, (surface.get_width() - hint.get_width() - 22, 28))
        tiles = self._layout(page)
        names = {d.app_id: d.name for d in self._context.app_catalog} if self._context else {}
        for app_id, rect in tiles.items():
            components.glass_card(surface, rect, theme, alpha=235, radius=26)
            components.icon(surface, ICONS[app_id], (rect.centerx, rect.y + 48), 46, theme.accent)
            label = render_text(names.get(app_id, app_id), 18, theme.text_primary, bold=True)
            surface.blit(label, label.get_rect(midtop=(rect.centerx, rect.y + 86)))
        components.page_dots(surface, page + 1, len(GRID) + 1, theme, 442)

    async def leave(self, reason: LeaveReason) -> None:
        del reason
        self._tiles.clear()

    async def dispose(self) -> None:
        self._context = None
