"""Fishing app: sea scene, HUD, shop/warehouse/codex modals."""

from __future__ import annotations

from typing import Any

import pygame

from deskcamdio.apps.fishing.economy import (
    BAIT_PACK,
    BAIT_PRICE,
    CAPSIZE_LOSS_COINS,
    CARGO_LIMIT_KG,
    RESCUE_BAIT,
    RESCUE_COST,
    SPECIES,
    PlayerState,
)
from deskcamdio.apps.fishing.world import HookState, World
from deskcamdio.core.lifecycle import App, LeaveReason, RouteState
from deskcamdio.core.runtime import RuntimeContext
from deskcamdio.ui import components
from deskcamdio.ui.aquarium import gradient
from deskcamdio.ui.themes import ThemeTokens
from deskcamdio.ui.typography import render_text

SEA_TOP = 96
PERIOD_LABELS = {"dawn": "清晨", "day": "白天", "dusk": "黄昏", "night": "夜晚"}


class FishingApp(App):
    def __init__(self) -> None:
        self._context: RuntimeContext | None = None
        self.world = World()
        self.player = PlayerState()
        self.modal: str | None = None
        self._dirty = False

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
        raw = await context.store.fetch_one("SELECT state_json FROM fishing_state WHERE id=1")
        if raw is not None:
            try:
                self.player = PlayerState.from_json(str(raw[0]))
            except Exception:  # noqa: BLE001 - corrupt save starts fresh
                self.player = PlayerState()

    async def enter(self, route: RouteState) -> None:
        self.modal = None
        self.world.hook_state = HookState.IDLE

    async def _save(self) -> None:
        context = self._context
        assert context is not None
        await context.store.save_fishing_state(self.player.to_json())
        self._dirty = False

    def handle_input(self, event: pygame.event.Event) -> None:
        context = self._context
        if context is None or event.type != pygame.MOUSEBUTTONDOWN:
            return
        pos = event.pos
        if event.pos[1] > SEA_TOP and self.modal is None:
            if self.world.hook_state is HookState.IDLE:
                self.world.cast()
                if self.player.energy <= 0:
                    self._error_flash()
            else:
                result = self.world.reel()
                if result == "qte-hit":
                    context.audio.play_sound("tap")
                if self.world.hook_state is HookState.LANDED:
                    self._land_fish()
        elif self.modal == "shop":
            self._shop_click(pos)

    def _error_flash(self) -> None:
        context = self._context
        assert context is not None
        context.audio.play_sound("error", category="error")

    def _land_fish(self) -> None:
        fish = self.world.current
        assert fish is not None
        self.player.cargo.append(dict(fish))
        self.world.current = None
        self.world.hook_state = HookState.IDLE
        self.player.energy = max(0, self.player.energy - 1)
        self._dirty = True
        context = self._context
        if context is not None and self.player.cargo_weight() > CARGO_LIMIT_KG:
            # Capsize: lose cargo and bait, pay rescue.
            self.player.coins = max(0, self.player.coins - CAPSIZE_LOSS_COINS)
            self.player.cargo.clear()
            self.player.bait = 0
            self._dirty = True
            context.audio.play_sound("alarm", category="alarm")

    def _shop_click(self, pos: tuple[int, int]) -> None:
        buy_rect = pygame.Rect(90, 250, 140, 48)
        rescue_rect = pygame.Rect(260, 250, 150, 48)
        close_rect = pygame.Rect(190, 326, 100, 48)
        if buy_rect.collidepoint(pos):
            cost = BAIT_PRICE * BAIT_PACK
            if self.player.coins >= cost:
                self.player.coins -= cost
                self.player.bait += BAIT_PACK
                self._dirty = True
        elif rescue_rect.collidepoint(pos):
            self.player.bait += RESCUE_BAIT
            self.player.coins = max(0, self.player.coins - min(RESCUE_COST, self.player.coins))
            self._dirty = True
        elif close_rect.collidepoint(pos) or not any(
            [buy_rect.collidepoint(pos), rescue_rect.collidepoint(pos)]
        ):
            self.modal = None

    def update(self, delta_seconds: float) -> None:
        self.world.update(delta_seconds)
        if self._dirty and self._context is not None:
            self._spawn(self._save())

    def render(self, surface: pygame.Surface) -> None:
        assert self._context is not None
        theme = self._context.theme.tokens
        gradient(surface, theme)
        sky_colors = {
            "dawn": (252, 200, 150),
            "day": (150, 205, 240),
            "dusk": (240, 160, 120),
            "night": (30, 42, 70),
        }
        pygame.draw.rect(surface, sky_colors[self.world.period], (0, 28, 480, SEA_TOP - 28))
        sea_color = (24, 92, 138) if self.world.period != "night" else (16, 44, 78)
        pygame.draw.rect(surface, sea_color, (0, SEA_TOP, 480, 480 - SEA_TOP))

        sun_color = (255, 221, 126) if self.world.period != "night" else (220, 230, 250)
        pygame.draw.circle(surface, sun_color, (404, 60), 17)
        for x in range(0, 480, 24):
            pygame.draw.line(surface, (255, 255, 255), (x, SEA_TOP + 24), (x + 12, SEA_TOP + 24), 2)
        pygame.draw.rect(surface, (103, 70, 46), (0, SEA_TOP + 52, 130, 18))
        for x in (16, 104):
            pygame.draw.rect(surface, (78, 52, 36), (x, SEA_TOP + 65, 14, 150))
        pygame.draw.rect(surface, (124, 84, 49), (350, SEA_TOP + 10, 130, 16))
        pygame.draw.rect(surface, (87, 57, 37), (444, SEA_TOP + 22, 13, 120))

        boat_color = (226, 178, 60) if self.player.golden_boat else theme.accent
        pygame.draw.polygon(
            surface,
            boat_color,
            [(210, SEA_TOP - 6), (270, SEA_TOP - 6), (262, SEA_TOP + 8), (218, SEA_TOP + 8)],
        )

        for index in range(8):
            wave_y = SEA_TOP + 14 + index * 44
            points = [(x + (index % 2) * 12, wave_y + ((x * 3) % 10)) for x in range(-20, 500, 60)]
            wave = pygame.Surface((480, 18), pygame.SRCALPHA)
            shifted = [(x, y - wave_y + 8) for x, y in points]
            pygame.draw.lines(wave, (255, 255, 255, 54), False, shifted, 2)
            surface.blit(wave, (0, wave_y - 8))

        if self.world.hook_state is HookState.IDLE:
            tip = pygame.Rect(105, 386, 270, 48)
            components.glass_card(surface, tip, theme, alpha=190, radius=15)
            text = render_text("点击海面抛竿", 17, (255, 255, 255), bold=True)
            surface.blit(text, text.get_rect(center=tip.center))

        if self.world.current is not None and self.world.hook_state is HookState.FIGHTING:
            fish_x, fish_y = 300, 300
            body_color = (240, 190, 60) if self.world.current["rare"] else (180, 220, 240)
            pygame.draw.circle(surface, body_color, (fish_x, fish_y), 18)
            if self.world.qte_active:
                ring_color = theme.warning
                radius = int(max(6.0, self.world.qte_ring_radius))
                pygame.draw.circle(surface, ring_color, (fish_x, fish_y), radius, width=3)

        hud = render_text(
            f"金币{self.player.coins} · 体力{self.player.energy} · 鱼饵{self.player.bait}"
            f" · {PERIOD_LABELS[self.world.period]}",
            15,
            (255, 255, 255),
            bold=True,
        )
        surface.blit(hud, hud.get_rect(midtop=(240, 34)))

        progress_rect = pygame.Rect(80, 440, 320, 12)
        pygame.draw.rect(surface, theme.surface_elevated, progress_rect, border_radius=6)
        if self.world.hook_state is HookState.FIGHTING:
            inner = progress_rect.copy()
            inner.width = max(12, int(progress_rect.width * self.world.progress))
            pygame.draw.rect(surface, theme.warning, inner, border_radius=6)

        if self.world.current is not None and self.world.hook_state in (
            HookState.FIGHTING,
            HookState.LANDED,
        ):
            name = render_text(
                f"{'★ ' if self.world.current['rare'] else ''}"
                f"{self.world.current['name']} {self.world.current['weight']}kg",
                17,
                (255, 255, 255),
            )
            surface.blit(name, name.get_rect(center=(240, 430)))

        cargo_weight = self.player.cargo_weight()
        cargo_text = render_text(
            f"舱载 {cargo_weight:.1f}/{CARGO_LIMIT_KG}kg", 14, theme.text_secondary
        )
        surface.blit(cargo_text, (16, 458))

        if self.modal == "shop":
            overlay = pygame.Surface((480, 480))
            overlay.set_alpha(160)
            overlay.fill((0, 0, 0))
            surface.blit(overlay, (0, 0))
            card = pygame.Rect(70, 170, 340, 230)
            pygame.draw.rect(surface, theme.surface, card, border_radius=18)
            title = render_text("商店", 22, theme.text_primary, bold=True)
            surface.blit(title, title.get_rect(center=(240, 200)))
            coins = render_text(f"金币 {self.player.coins}", 16, theme.text_secondary)
            surface.blit(coins, coins.get_rect(center=(240, 228)))
            components_button(
                surface, pygame.Rect(90, 250, 140, 48), f"鱼饵×{BAIT_PACK} {BAIT_PRICE}金", theme
            )
            components_button(
                surface, pygame.Rect(260, 250, 150, 48), f"救济 {RESCUE_BAIT}份", theme
            )
            components_button(surface, pygame.Rect(190, 326, 100, 48), "关闭", theme)

    async def leave(self, reason: LeaveReason) -> None:
        if reason is not LeaveReason.SHUTDOWN:
            await self._save()
            self.world.current = None
            self.world.hook_state = HookState.IDLE

    async def dispose(self) -> None:
        await self._save()
        self._context = None


def components_button(
    surface: pygame.Surface, rect: pygame.Rect, label: str, theme: ThemeTokens
) -> None:
    from deskcamdio.ui.components import button as draw_button

    draw_button(surface, rect, label, theme, size=16)


def species_count(player: PlayerState) -> int:
    """Total codex entries unlocked across species × rare."""
    return len({tuple(key.split(":")) for key in player.collection})


def codex_total() -> int:
    return len(SPECIES) * 2
