"""GBA page: ROM library indexing, list and launch requests."""

from __future__ import annotations

import logging

import pygame

from deskcamdio.core.lifecycle import App, LeaveReason, RouteState
from deskcamdio.core.runtime import RuntimeContext
from deskcamdio.ui import art, components
from deskcamdio.ui.aquarium import ambient, seabed
from deskcamdio.ui.pager import PagePager
from deskcamdio.ui.typography import draw_wrapped, render_text

LOGGER = logging.getLogger(__name__)
ROMS_PER_PAGE = 5


class GbaApp(App):
    def __init__(self) -> None:
        self._context: RuntimeContext | None = None
        self.roms: list[dict] = []
        self._rows: dict[str, pygame.Rect] = {}
        self._page_buttons: dict[str, pygame.Rect] = {}
        self.pager = PagePager(1)
        self._drag_start: tuple[int, int] | None = None
        self._error = ""
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
        context = self._context
        assert context is not None

        roms_dir = context.data_dir / "roms" / "gba"
        if roms_dir.parent.exists():
            from deskcamdio.services.rom_library import index_directory

            try:
                await index_directory(roms_dir, context.store)
            except Exception:  # noqa: BLE001 - a bad ROM must not break the page
                LOGGER.exception("rom indexing failed")

        rows = await context.store.fetch_all(
            "SELECT sha256, title, game_code, size_bytes, last_played_at"
            " FROM gba_roms ORDER BY title"
        )
        self.roms = [
            {
                "sha256": r[0],
                "title": r[1],
                "game_code": r[2],
                "size_bytes": r[3],
                "last_played_at": r[4],
            }
            for r in rows
        ]
        self.pager.set_page_count(self.page_count)
        self.pager.set_index(int(route.args.get("page", self.page)))

    @property
    def page_count(self) -> int:
        return max(1, (len(self.roms) + ROMS_PER_PAGE - 1) // ROMS_PER_PAGE)

    def handle_input(self, event: pygame.event.Event) -> None:
        context = self._context
        if context is None:
            return
        if event.type == pygame.MOUSEBUTTONDOWN and getattr(event, "button", 1) == 1:
            self._drag_start = event.pos
            self.pager.begin_drag(event.pos[0])
        elif event.type == pygame.MOUSEMOTION and self._drag_start is not None:
            self.pager.drag_to(event.pos[0])
        elif event.type == pygame.MOUSEBUTTONUP and getattr(event, "button", 1) == 1:
            if self._drag_start is None:
                return
            self._finish_pointer(event.pos, context)
            self._drag_start = None

    def _finish_pointer(self, pos: tuple[int, int], context: RuntimeContext) -> None:
        assert self._drag_start is not None
        if self.pager.end_drag(pos[0]):
            return
        action = components.hit_test(self._page_buttons, pos)
        if action == "previous" and self.page > 0:
            self.pager.move(-1)
            return
        if action == "next" and self.page < self.page_count - 1:
            self.pager.move(1)
            return
        for sha256, rect in self._rows.items():
            if rect.collidepoint(pos):
                asyncio_start_launch(context, sha256)
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
        header = render_text("GBA 游戏库", 20, theme.text_primary, bold=True)
        surface.blit(header, (16, 12))
        hint = render_text(
            "用 SCP 把 .gba 放进 /var/lib/deskcamdio/roms/gba/", 14, theme.text_secondary
        )
        surface.blit(hint, (16, 40))

        if interactive:
            self._rows.clear()
            self._page_buttons.clear()
        first = page * ROMS_PER_PAGE
        visible = self.roms[first : first + ROMS_PER_PAGE]
        for index, rom in enumerate(visible):
            rect = pygame.Rect(16, 60 + index * 66, 448, 58)
            size_mb = rom["size_bytes"] / (1024 * 1024)
            components.row(
                surface,
                rect,
                str(rom["title"]),
                theme,
                trailing=f"{rom['game_code']} · {size_mb:.1f}MB",
                selected=False,
            )
            if interactive:
                self._rows[str(rom["sha256"])] = rect

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
            page_label = render_text(
                f"{page + 1} / {self.page_count}  ·  左右滑动翻页",
                14,
                theme.text_secondary,
            )
            surface.blit(page_label, page_label.get_rect(center=(216, 426)))

        if not self.roms:
            seabed(surface, theme, elapsed * 0.2)
            card = pygame.Rect(48, 92, 384, 226)
            components.glass_card(surface, card, theme, alpha=216)
            art.blit_centered(surface, "gba-cartridge-96x128-v1.png", (132, 196), (72, 96))
            empty = render_text("还没有 GBA 游戏", 20, theme.text_primary, bold=True)
            surface.blit(empty, (196, 126))
            draw_wrapped(
                surface,
                "导入 .gba ROM 后会自动出现在这里",
                pygame.Rect(196, 162, 210, 50),
                15,
                theme.text_secondary,
            )
            status = render_text("蓝牙 / USB 手柄", 14, theme.accent, bold=True)
            surface.blit(status, (196, 228))
            exit_hint = render_text("EC11 可紧急退出", 13, theme.text_secondary)
            surface.blit(exit_hint, (196, 254))

    async def leave(self, reason: LeaveReason) -> None:
        del reason

    async def dispose(self) -> None:
        self._context = None
        self.roms.clear()
        self._rows.clear()
        self._page_buttons.clear()
        self._drag_start = None


def asyncio_start_launch(context: RuntimeContext, sha256: str) -> None:
    """GameSession launch lands with Phase E wiring; publish intent now."""
    context.bus.publish("gba.launch_requested", sha256=sha256)
