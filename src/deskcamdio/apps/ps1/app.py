"""PlayStation game library backed by RetroArch/PCSX-ReARMed."""

from __future__ import annotations

from pathlib import Path

import pygame

from deskcamdio.core.lifecycle import App, LeaveReason, RouteState
from deskcamdio.core.runtime import RuntimeContext
from deskcamdio.services.ps1_library import scan_ps1_directory
from deskcamdio.ui import art, components
from deskcamdio.ui.aquarium import ambient, seabed
from deskcamdio.ui.pager import PagePager
from deskcamdio.ui.typography import draw_wrapped, render_text

ITEMS_PER_PAGE = 5


class Ps1App(App):
    def __init__(self) -> None:
        self._context: RuntimeContext | None = None
        self.games: list[Path] = []
        self.pager = PagePager(1)
        self._rows: list[tuple[Path, pygame.Rect]] = []
        self._page_buttons: dict[str, pygame.Rect] = {}
        self._drag_start: tuple[int, int] | None = None
        self._page_surface = pygame.Surface((480, 480))

    @property
    def page(self) -> int:
        return self.pager.index

    @property
    def preferred_fps(self) -> int:
        return 60 if self.pager.is_animating or self.pager.is_dragging else 0

    async def mount(self, context: RuntimeContext) -> None:
        self._context = context

    async def enter(self, route: RouteState) -> None:
        assert self._context is not None
        self.games = scan_ps1_directory(self._context.data_dir / "roms" / "ps1")
        self.pager.set_page_count(self.page_count)
        self.pager.set_index(int(route.args.get("page", self.page)))

    @property
    def page_count(self) -> int:
        return max(1, (len(self.games) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)

    def handle_input(self, event: pygame.event.Event) -> None:
        if self._context is None:
            return
        if event.type == pygame.MOUSEBUTTONDOWN and getattr(event, "button", 1) == 1:
            self._drag_start = event.pos
            self.pager.begin_drag(event.pos[0])
        elif event.type == pygame.MOUSEMOTION and self._drag_start is not None:
            self.pager.drag_to(event.pos[0])
        elif event.type == pygame.MOUSEBUTTONUP and self._drag_start is not None:
            self._finish_pointer(event.pos)
            self._drag_start = None

    def _finish_pointer(self, pos: tuple[int, int]) -> None:
        assert self._context is not None and self._drag_start is not None
        if self.pager.end_drag(pos[0]):
            return
        action = components.hit_test(self._page_buttons, pos)
        if action == "previous" and self.page > 0:
            self.pager.move(-1)
            return
        if action == "next" and self.page < self.page_count - 1:
            self.pager.move(1)
            return
        for path, rect in self._rows:
            if rect.collidepoint(pos):
                self._context.bus.publish("ps1.launch_requested", path=str(path))
                return

    def update(self, delta_seconds: float) -> None:
        self.pager.update(delta_seconds)

    def render(self, surface: pygame.Surface) -> None:
        for page in self.pager.visible_pages():
            self._page_surface.fill((0, 0, 0))
            self._render_page(self._page_surface, page, interactive=page == self.page)
            surface.blit(self._page_surface, (self.pager.page_x(page), 0))

    def _render_page(self, surface: pygame.Surface, page: int, *, interactive: bool) -> None:
        assert self._context is not None
        theme = self._context.theme.tokens
        elapsed = pygame.time.get_ticks() / 1000.0
        ambient(surface, theme, elapsed * 0.3)
        title = render_text("PlayStation 游戏库", 20, theme.text_primary, bold=True)
        surface.blit(title, (16, 12))
        hint = render_text("RetroArch · PCSX-ReARMed · 四肩键退出", 14, theme.text_secondary)
        surface.blit(hint, (16, 40))

        first = page * ITEMS_PER_PAGE
        if interactive:
            self._rows.clear()
            self._page_buttons.clear()
        for index, path in enumerate(self.games[first : first + ITEMS_PER_PAGE]):
            rect = pygame.Rect(16, 60 + index * 66, 448, 58)
            components.row(
                surface,
                rect,
                path.stem,
                theme,
                trailing=f"PS1 · {path.stat().st_size / (1024 * 1024):.0f}MB",
                size=17,
            )
            if interactive:
                self._rows.append((path, rect))

        if self.page_count > 1:
            previous = pygame.Rect(16, 400, 104, 52)
            following = pygame.Rect(312, 400, 108, 52)
            if page > 0:
                components.ghost_button(surface, previous, "上一页", theme, size=16)
                if interactive:
                    self._page_buttons["previous"] = previous
            if page < self.page_count - 1:
                components.ghost_button(surface, following, "下一页", theme, size=16)
                if interactive:
                    self._page_buttons["next"] = following
            label = render_text(f"{page + 1} / {self.page_count}", 14, theme.text_secondary)
            surface.blit(label, label.get_rect(center=(216, 426)))

        if not self.games:
            seabed(surface, theme, elapsed * 0.2)
            components.glass_card(surface, pygame.Rect(48, 92, 384, 226), theme, alpha=216)
            art.blit_centered(surface, "ps1-disc-case-96x128-v1.png", (132, 196), (72, 96))
            empty = render_text("还没有 PS1 游戏", 20, theme.text_primary, bold=True)
            surface.blit(empty, (196, 126))
            draw_wrapped(
                surface,
                "导入 CUE/BIN、CHD、PBP 或 ISO",
                pygame.Rect(196, 162, 210, 52),
                15,
                theme.text_secondary,
            )
            status = render_text("蓝牙 / USB 手柄", 14, theme.accent, bold=True)
            surface.blit(status, (196, 228))
            exit_hint = render_text("四肩键组合退出", 13, theme.text_secondary)
            surface.blit(exit_hint, (196, 254))

    async def leave(self, reason: LeaveReason) -> None:
        del reason

    async def dispose(self) -> None:
        self._context = None
        self.games.clear()
        self._rows.clear()
        self._page_buttons.clear()
