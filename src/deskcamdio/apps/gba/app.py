"""GBA page: ROM library indexing, list and launch requests."""

from __future__ import annotations

import logging

import pygame

from deskcamdio.core.lifecycle import App, LeaveReason, RouteState
from deskcamdio.core.runtime import RuntimeContext
from deskcamdio.ui import components
from deskcamdio.ui.aquarium import ambient, seabed
from deskcamdio.ui.typography import render_text

LOGGER = logging.getLogger(__name__)


class GbaApp(App):
    def __init__(self) -> None:
        self._context: RuntimeContext | None = None
        self.roms: list[dict] = []
        self._rows: dict[str, pygame.Rect] = {}
        self._error = ""

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

    def handle_input(self, event: pygame.event.Event) -> None:
        context = self._context
        if context is None or event.type != pygame.MOUSEBUTTONDOWN:
            return
        for sha256, rect in self._rows.items():
            if rect.collidepoint(event.pos):
                asyncio_start_launch(context, sha256)
                break

    def update(self, delta_seconds: float) -> None:
        del delta_seconds

    def render(self, surface: pygame.Surface) -> None:
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

        self._rows.clear()
        for index, rom in enumerate(self.roms[:5]):
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
            self._rows[str(rom["sha256"])] = rect

        if not self.roms:
            seabed(surface, theme, elapsed * 0.2)
            card = pygame.Rect(48, 92, 384, 226)
            components.glass_card(surface, card, theme, alpha=216)
            components.icon(surface, "player-play", (240, 148), 40, theme.accent)
            empty = render_text("还没有 GBA 游戏", 20, theme.text_primary, bold=True)
            surface.blit(empty, empty.get_rect(center=(240, 202)))
            sub = render_text("导入 .gba ROM 后会自动出现在这里", 15, theme.text_secondary)
            surface.blit(sub, sub.get_rect(center=(240, 235)))
            status = render_text("手柄支持热插拔 · EC11 可紧急退出", 14, theme.text_secondary)
            surface.blit(status, status.get_rect(center=(240, 278)))

    async def leave(self, reason: LeaveReason) -> None:
        del reason

    async def dispose(self) -> None:
        self._context = None
        self.roms.clear()
        self._rows.clear()


def asyncio_start_launch(context: RuntimeContext, sha256: str) -> None:
    """GameSession launch lands with Phase E wiring; publish intent now."""
    context.bus.publish("gba.launch_requested", sha256=sha256)
