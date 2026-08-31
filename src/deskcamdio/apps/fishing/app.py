from __future__ import annotations

import json
import math
import random
import time
from dataclasses import asdict, dataclass
from importlib.resources import files
from typing import Any

import pygame

from deskcamdio.apps.fishing import legacy_ui as ui
from deskcamdio.apps.fishing.economy import UPGRADE_COSTS, PlayerState
from deskcamdio.apps.fishing.sprite import SpriteSheetAnimator
from deskcamdio.apps.fishing.world import FishingWorld, ReelResult
from deskcamdio.core.lifecycle import App, LeaveReason, RouteState
from deskcamdio.core.runtime import RuntimeContext
from deskcamdio.ui import renderer


@dataclass(slots=True)
class GameModal:
    title: str
    body: str
    timer: float
    color: tuple[int, int, int]


class FishingApp(App):
    def __init__(self) -> None:
        self.context: RuntimeContext | None = None
        self.player = PlayerState()
        self.at_sea = False
        self.bait_left = 20
        self.cargo: list[dict[str, int | str]] = []
        self.warehouse: list[dict[str, int | str]] = []
        self.dock_tab = "warehouse"
        self.modal: GameModal | None = None
        self.coin_jump = 0
        self.coin_jump_timer = 0.0
        self.world = FishingWorld(random.Random(807), 10)
        self.animators: dict[int, SpriteSheetAnimator] = {}
        self.elapsed = 0.0
        self.checkpoint_elapsed = 0.0
        self.world_accumulator = 0.0
        self.reel_state = "idle"
        self.reel_return_depth = 230.0
        self.reel_hold = 0.0
        self.return_after_reel = False
        self.drag_mode = ""
        self.sail_button = pygame.Rect(260, 360, 196, 48)
        self.warehouse_tab = pygame.Rect(24, 80, 205, 38)
        self.shop_tab = pygame.Rect(251, 80, 205, 38)
        self.sell_button = pygame.Rect(24, 360, 196, 48)
        self.buy_bait_button = pygame.Rect(24, 360, 196, 48)
        self.return_button = pygame.Rect(12, 34, 68, 30)
        self.reel_button = pygame.Rect(397, 365, 68, 48)
        self.upgrade_buttons = {
            "boat": pygame.Rect(300, 123, 145, 52),
            "rod": pygame.Rect(300, 195, 145, 52),
            "bait": pygame.Rect(300, 267, 145, 52),
        }
        self._was_hooked = False
        self.return_after_reel = False
        self._warehouse_fish_frames: dict[tuple[str, str], pygame.Surface] = {}
        self._fishing_prop_frames: dict[tuple[str, float], pygame.Surface] = {}
        self._sea_background: pygame.Surface | None = None
        self._dirty = False
        self._save_revision = 0
        self._save_task: Any = None

    async def mount(self, context: RuntimeContext) -> None:
        self.context = context
        row = await context.store.fetch_one("SELECT state_json FROM fishing_state WHERE id=1")
        if row is not None:
            self._restore(str(row[0]))
        self.world = FishingWorld(random.Random())

    async def enter(self, route: RouteState) -> None:
        del route
        assert self.context is not None
        ui.use_theme(self.context.theme.tokens)

    def _restore(self, raw: str) -> None:
        try:
            data = json.loads(raw)
            if "player" in data:
                self.player = PlayerState(**data["player"])
                self.at_sea = bool(data.get("at_sea", False))
                self.bait_left = int(data.get("bait_left", 20))
                self.cargo = list(data.get("cargo", []))
                self.warehouse = list(data.get("warehouse", []))
            else:
                # Migrate the simplified v1 save into the richer legacy game.
                self.player.coins = int(data.get("coins", self.player.coins))
                self.player.energy = int(data.get("energy", self.player.energy))
                self.player.rod_level = max(1, min(3, int(data.get("rod_level", 1))))
                self.bait_left = int(data.get("bait", 20))
                self.warehouse = [self._migrate_fish(item) for item in data.get("cargo", [])]
        except (TypeError, ValueError, json.JSONDecodeError):
            self.player = PlayerState(last_energy_at=time.time())

    @staticmethod
    def _migrate_fish(item: dict[str, Any]) -> dict[str, int | str]:
        weight = max(1, round(float(item.get("weight", 1))))
        size = "small" if weight <= 2 else "medium" if weight <= 5 else "large"
        return {
            "name": str(item.get("name", "未知鱼")),
            "size": size,
            "weight": weight,
            "value": int(item.get("value", 1)),
        }

    def deactivate(self) -> None:
        self._warehouse_fish_frames.clear()
        self._fishing_prop_frames.clear()
        self._sea_background = None

    def _save(self) -> None:
        self._dirty = True
        self._save_revision += 1

    async def _flush_save(self) -> None:
        if not self._dirty or self.context is None:
            return
        revision = self._save_revision
        payload = json.dumps(
            {
                "format": 2,
                "player": asdict(self.player),
                "at_sea": self.at_sea,
                "bait_left": self.bait_left,
                "cargo": self.cargo,
                "warehouse": self.warehouse,
            },
            ensure_ascii=False,
        )
        await self.context.store.save_fishing_state(payload)
        if revision == self._save_revision:
            self._dirty = False

    def _schedule_save(self) -> None:
        if not self._dirty or (self._save_task is not None and not self._save_task.done()):
            return
        assert self.context is not None
        if self.context.scope is not None:
            self._save_task = self.context.scope.create_task(
                self._flush_save(), name="fishing-save"
            )
        else:
            import asyncio

            self._save_task = asyncio.get_running_loop().create_task(self._flush_save())

    def _sound(self, name: str, *, category: str = "game") -> None:
        del category
        if self.context is None:
            return
        mapped = "alarm" if name == "game_escape" else "error" if name == "error" else "tap"
        sound_category = "alarm" if mapped == "alarm" else "error" if mapped == "error" else "ui"
        self.context.audio.play_sound(mapped, category=sound_category)

    def _show_modal(
        self,
        title: str,
        body: str,
        duration: float = 1.5,
        color: tuple[int, int, int] = (89, 180, 255),
    ) -> None:
        self.modal = GameModal(title, body, duration, color)

    def _start_trip(self) -> None:
        assert self.context is not None
        if self.player.energy <= 0:
            self._sound("error", category="game")
            self._show_modal("体力不足", "休息一会儿再出海吧", 1.5, ui.AMBER)
            return
        if self.bait_left <= 0:
            self._sound("error", category="game")
            self.dock_tab = "shop"
            self._show_modal("没有鱼饵", "先到商店购买鱼饵", 1.8, ui.AMBER)
            return
        self.at_sea = True
        self.cargo = []
        self.world = FishingWorld(random.Random())
        self.animators.clear()
        self._reset_reel_state()
        self._save()
        self._sound("sail", category="game")

    def _return_to_dock(self) -> None:
        self.warehouse.extend(self.cargo)
        self.at_sea = False
        self.cargo = []
        self.dock_tab = "warehouse"
        self._reset_reel_state()
        self.player.last_energy_at = time.time()
        self._save()
        if self.context:
            self._sound("back", category="game")

    def _reset_reel_state(self) -> None:
        self.reel_state = "idle"
        self.reel_hold = 0.0
        self.reel_return_depth = self.world.hook_depth
        self.drag_mode = ""
        self._was_hooked = False

    def _capsize(self, extra_value: int = 0) -> None:
        lost_count = len(self.cargo) + (1 if extra_value else 0)
        lost_value = sum(int(item["value"]) for item in self.cargo) + extra_value
        rescue_fee = min(100, self.player.coins)
        self.player.coins -= rescue_fee
        self.cargo = []
        self.bait_left = 0
        self.at_sea = False
        self.dock_tab = "warehouse"
        self._reset_reel_state()
        self.player.last_energy_at = time.time()
        self._save()
        if self.context:
            self._sound("game_escape", category="game")
        self._show_modal(
            "船翻了！",
            f"损失{lost_count}条鱼（价值{lost_value}），支付{rescue_fee}金币救援费",
            0,
            ui.RED,
        )

    def debug_grant(self, *, coins: int = 0, energy: int = 0) -> None:
        self.player.coins = max(0, self.player.coins + coins)
        self.player.energy = min(100, max(0, self.player.energy + energy))
        self._save()

    def _sell_all(self) -> None:
        assert self.context is not None
        if not self.warehouse:
            self._sound("error", category="game")
            self._show_modal("仓库是空的", "出海钓几条鱼再回来吧", 1.4, ui.MUTED)
            return
        earned = sum(int(item["value"]) for item in self.warehouse)
        self.warehouse.clear()
        self.player.coins += earned
        self.coin_jump = earned
        self.coin_jump_timer = 1.2
        self._save()
        self._sound("coin", category="game")

    def _buy_bait(self) -> None:
        assert self.context is not None
        if self._can_claim_rescue_bait():
            self.bait_left = 5
            self._show_modal("获得救济鱼饵", "送你5份鱼饵，重新出海吧", 1.5, ui.GREEN)
            self._save()
            self._sound("success", category="game")
            return
        if self.player.coins < 20:
            self._sound("error", category="game")
            self._show_modal("金币不足", "5份鱼饵需要20金币", 1.4, ui.AMBER)
            return
        self.player.coins -= 20
        self.bait_left += 5
        self._save()
        self._sound("coin", category="game")

    def _can_claim_rescue_bait(self) -> bool:
        return (
            not self.at_sea
            and self.bait_left == 0
            and self.player.coins < 20
            and not self.warehouse
            and not self.cargo
        )

    def _upgrade(self, kind: str) -> None:
        assert self.context is not None
        if self.player.upgrade(kind):
            self._save()
            self._sound("success", category="game")
        else:
            self._sound("error", category="game")

    def _reel(self) -> None:
        if not self.at_sea or self.reel_state != "idle":
            return
        self.reel_state = "raising"
        self.reel_return_depth = self.world.hook_target_depth
        self.world.set_hook_target(125)
        self.player.energy = max(0, self.player.energy - 1)
        result = self.world.begin_reel()
        if result.status == "started":
            self.bait_left = max(0, self.bait_left - 1)
        self.return_after_reel = self.player.energy == 0
        self._save()
        if self.context:
            self._sound("game_reel", category="game")

    def _complete_catch(self, result: ReelResult) -> None:
        weight = result.weight
        value = result.value
        name = result.name
        size = result.size
        if self.cargo_weight + weight > self.player.capacity:
            self._capsize(value)
            return
        self.cargo.append({"name": name, "size": size, "weight": weight, "value": value})
        if self.context:
            self._sound("game_catch", category="game")
        self._show_modal(
            f"钓到了{name}！",
            f"重量{weight} · 价值{value}金币",
            1.2,
            ui.GREEN,
        )
        self._save()

    def _reel_speed(self) -> float:
        fish = self.world.hooked
        if fish is None or fish.state != "reeling":
            return 160.0
        base = {"small": 145.0, "medium": 95.0, "large": 58.0}[fish.size]
        return base * (1.0 + (self.player.rod_level - 1) * 0.15)

    @property
    def cargo_weight(self) -> int:
        return sum(int(item["weight"]) for item in self.cargo)

    def handle_input(self, event: pygame.event.Event) -> None:  # noqa: C901 - legacy game flow
        if self.modal is not None:
            if event.type == pygame.MOUSEBUTTONDOWN:
                self.modal = None
            return
        if event.type == pygame.KEYDOWN and event.key == pygame.K_SPACE:
            self._reel()
            return
        if not self.at_sea:
            if event.type != pygame.MOUSEBUTTONDOWN:
                return
            if self.sail_button.collidepoint(event.pos):
                self._start_trip()
                return
            if self.warehouse_tab.collidepoint(event.pos):
                self.dock_tab = "warehouse"
            elif self.shop_tab.collidepoint(event.pos):
                self.dock_tab = "shop"
            elif self.dock_tab == "warehouse" and self.sell_button.collidepoint(event.pos):
                self._sell_all()
            elif self.dock_tab == "shop" and self.buy_bait_button.collidepoint(event.pos):
                self._buy_bait()
            elif self.dock_tab == "shop":
                for kind, rect in self.upgrade_buttons.items():
                    if rect.collidepoint(event.pos):
                        self._upgrade(kind)
                        return
            return
        if event.type == pygame.MOUSEBUTTONUP:
            self.drag_mode = ""
        elif event.type == pygame.MOUSEBUTTONDOWN:
            if self.return_button.collidepoint(event.pos):
                self._return_to_dock()
            elif self.reel_button.collidepoint(event.pos):
                self._reel()
            elif event.pos[0] >= 410 and 105 <= event.pos[1] <= 365:
                self.drag_mode = "hook"
                self.world.set_hook_target(event.pos[1])
            elif event.pos[1] <= 112:
                self.drag_mode = "boat"
                self.world.set_boat_target(event.pos[0])
        elif event.type == pygame.MOUSEMOTION and event.buttons[0]:
            if self.drag_mode == "hook":
                self.world.set_hook_target(event.pos[1])
            elif self.drag_mode == "boat":
                self.world.set_boat_target(event.pos[0])

    def update(self, delta_seconds: float) -> None:  # noqa: C901 - legacy simulation flow
        self._schedule_save()
        self.elapsed += delta_seconds
        if self.modal and self.modal.timer > 0:
            self.modal.timer -= delta_seconds
            if self.modal.timer <= 0:
                self.modal = None
        if self.coin_jump_timer > 0:
            self.coin_jump_timer = max(0.0, self.coin_jump_timer - delta_seconds)
        if self.modal is not None:
            return
        if not self.at_sea:
            before = self.player.energy
            self.player.recover_energy(time.time())
            if before != self.player.energy:
                self._save()
            return
        self.world_accumulator += min(delta_seconds, 0.25)
        while self.world_accumulator >= 1 / 30:
            self.world.update(
                1 / 30,
                self.player,
                can_bite=self.bait_left > 0 and self.reel_state == "idle",
                hook_speed=self._reel_speed(),
            )
            self.world_accumulator -= 1 / 30
        if self.reel_state == "raising" and self.world.hook_depth <= 128:
            landed = self.world.land_reeling()
            if landed.status == "caught":
                self._complete_catch(landed)
                if not self.at_sea:
                    return
            if self.return_after_reel:
                self._return_to_dock()
                return
            self.reel_state = "holding"
            self.reel_hold = 0.22
        elif self.reel_state == "holding":
            self.reel_hold -= delta_seconds
            if self.reel_hold <= 0:
                self.reel_state = "lowering"
                self.world.set_hook_target(self.reel_return_depth)
        elif (
            self.reel_state == "lowering"
            and abs(self.world.hook_depth - self.reel_return_depth) <= 3
        ):
            self.reel_state = "idle"
            self.world.reset_bite_checks()
        hooked = self.world.hooked is not None
        if hooked and not self._was_hooked and self.context:
            self._sound("game_bite", category="game")
        self._was_hooked = hooked
        for event_name in self.world.pop_events():
            if event_name == "bite_timeout":
                if self.context:
                    self._sound("game_escape", category="game")
                self.bait_left = max(0, self.bait_left - 1)
                body = "鱼饵也用完了，请返航购买" if self.bait_left <= 0 else "收线太慢，鱼挣脱了"
                self._show_modal("鱼跑了！", body, 1.2, ui.AMBER)
                self.world.reset_bite_checks()
                self._save()
            elif event_name == "reel_escaped":
                if self.context:
                    self._sound("game_escape", category="game")
                body = "鱼饵也用完了，请返航购买" if self.bait_left <= 0 else "遛鱼时挣脱了鱼钩"
                self._show_modal("鱼跑了！", body, 1.2, ui.AMBER)
                self._save()
        self.checkpoint_elapsed += delta_seconds
        if self.checkpoint_elapsed >= 5.0:
            self.checkpoint_elapsed = 0.0
            self._save()

    def render(self, surface: pygame.Surface) -> None:
        assert self.context is not None
        ui.use_theme(self.context.theme.tokens)
        if self.at_sea:
            self._render_sea(surface)
        else:
            renderer.background(surface, self.context.theme.tokens)
            self._render_dock(surface)
        if self.modal:
            self._render_modal(surface)

    def _render_dock(self, surface: pygame.Surface) -> None:
        assert self.context is not None
        palette = ui.palette()
        ui.header(surface, "渔港", "", "sailboat")
        coin_center = (354, 51)
        self._draw_coin(surface, coin_center, 11)
        ui.text(surface, f"{self.player.coins}", (373, 38), 17, palette.warning, bold=True)
        if self.coin_jump_timer > 0:
            progress = self.coin_jump_timer / 1.2
            jump_y = int(48 - math.sin((1 - progress) * math.pi) * 20)
            ui.text(surface, f"+{self.coin_jump}", (290, jump_y), 19, palette.success, bold=True)
        ui.button(surface, self.warehouse_tab, "仓库", active=self.dock_tab == "warehouse")
        ui.button(surface, self.shop_tab, "商店", active=self.dock_tab == "shop")
        if self.dock_tab == "warehouse":
            self._render_warehouse(surface)
        else:
            self._render_shop(surface)
        ui.button(
            surface, self.sail_button, "出海", active=self.player.energy > 0 and self.bait_left > 0
        )

    def _render_warehouse(self, surface: pygame.Surface) -> None:
        assert self.context is not None
        palette = ui.palette()
        ui.text(
            surface,
            f"体力 {self.player.energy}/100   鱼饵 {self.bait_left}   库存 {len(self.warehouse)}",
            (24, 132),
            14,
            palette.muted,
        )
        if not self.warehouse:
            ui.icon(surface, "fish", (240, 205), 46, palette.accent, center=True)
            ui.text(surface, "仓库里还没有鱼", (240, 249), 20, palette.text, bold=True, center=True)
            ui.text(surface, "出海钓几条鱼再回来吧", (240, 275), 14, palette.muted, center=True)
        for index, item in enumerate(self.warehouse[:5]):
            y = 151 + index * 39
            ui.glass_card(
                surface, pygame.Rect(24, y, 432, 36), tint=palette.surface, radius=12, alpha=225
            )
            thumbnail = self._warehouse_fish(item)
            surface.blit(thumbnail, thumbnail.get_rect(center=(51, y + 18)))
            name = str(item.get("name") or "未知鱼")
            ui.text(surface, name, (78, y + 6), 16, palette.text, bold=True)
            ui.text(surface, f"{item['weight']} 重", (235, y + 8), 13, palette.muted)
            self._draw_coin(surface, (363, y + 18), 8)
            ui.text(
                surface,
                f"{item['value']}",
                (376, y + 7),
                14,
                palette.warning,
                bold=True,
            )
        if len(self.warehouse) > 5:
            ui.text(
                surface,
                f"还有 {len(self.warehouse) - 5} 条",
                (240, 344),
                13,
                palette.muted,
                center=True,
            )
        ui.button(surface, self.sell_button, "卖出全部", active=bool(self.warehouse))

    def _render_shop(self, surface: pygame.Surface) -> None:
        assert self.context is not None
        palette = ui.palette()
        ui.text(
            surface,
            f"体力 {self.player.energy}/100   当前鱼饵 {self.bait_left}",
            (24, 132),
            14,
            palette.muted,
        )
        labels = {"boat": "渔船", "rod": "鱼竿", "bait": "鱼饵"}
        effects = {
            "boat": f"容量 {self.player.capacity}",
            "rod": f"中鱼 {int(self.player.hook_chance * 100)}%",
            "bait": f"咬钩 {int(self.player.bite_chance * 100)}%",
        }
        for index, kind in enumerate(("boat", "rod", "bait")):
            y = 156 + index * 62
            level = int(getattr(self.player, f"{kind}_level"))
            ui.glass_card(
                surface, pygame.Rect(24, y, 432, 54), tint=palette.surface, radius=16, alpha=222
            )
            ui.text(
                surface, f"{labels[kind]}  Lv.{level}", (40, y + 8), 19, palette.text, bold=True
            )
            ui.text(surface, effects[kind], (40, y + 32), 14, palette.muted)
            self.upgrade_buttons[kind].y = y + 1
            if level < 3:
                cost = UPGRADE_COSTS[kind][level - 1]
                ui.button(surface, self.upgrade_buttons[kind], f"升级  {cost}")
            else:
                ui.button(surface, self.upgrade_buttons[kind], "已满级", active=True)
        rescue = self._can_claim_rescue_bait()
        ui.button(
            surface,
            self.buy_bait_button,
            "免费领5份" if rescue else "买5份  20",
            active=rescue,
        )

    def _render_modal(self, surface: pygame.Surface) -> None:
        assert self.modal is not None
        ui.modal(
            surface,
            self.modal.title,
            self.modal.body,
            color=self.modal.color,
            persistent=self.modal.timer <= 0,
        )

    def _render_sky(self, surface: pygame.Surface, top: int, bottom: int) -> None:
        for y in range(top, bottom):
            ratio = y / max(1, bottom)
            pygame.draw.line(
                surface,
                (int(20 - ratio * 8), int(95 - ratio * 43), int(126 - ratio * 50)),
                (0, y),
                (480, y),
            )

    def _render_sea(self, surface: pygame.Surface) -> None:
        if self._sea_background is None:
            background = pygame.Surface((480, 480))
            pygame.draw.rect(background, (54, 137, 169), (0, 0, 480, 76))
            for y in range(76, 480):
                ratio = (y - 76) / 404
                color = (
                    int(9 - ratio * 3),
                    int(75 - ratio * 40),
                    int(105 - ratio * 45),
                )
                pygame.draw.line(background, color, (0, y), (480, y))
            pygame.draw.line(background, (136, 213, 222), (0, 76), (480, 76), 3)
            self._sea_background = background
        surface.blit(self._sea_background, (0, 0))
        self._render_decor(surface)
        shake = math.sin(self.elapsed * 38) * 4 if self.world.hooked else 0
        line_x = int(self.world.boat_x + 15 + shake)
        pygame.draw.line(
            surface,
            (224, 229, 215),
            (int(self.world.boat_x + 15), 66),
            (line_x, int(self.world.hook_depth)),
            2,
        )
        pygame.draw.circle(surface, (242, 96, 72), (line_x, 79), 5)
        pygame.draw.arc(
            surface,
            (205, 215, 211),
            (line_x - 3, int(self.world.hook_depth) - 2, 12, 14),
            math.pi * 0.1,
            math.pi * 1.6,
            2,
        )
        for fish in self.world.fish:
            animator = self.animators.get(fish.fish_id)
            if animator is None:
                animator = SpriteSheetAnimator.fish(fish.color)
                self.animators[fish.fish_id] = animator
            clip = "attack" if fish.state == "bite" else "swim"
            animator.set_clip(clip)
            animator.update(1 / 30)
            size = {"small": 48, "medium": 64, "large": 88}[fish.size]
            image = animator.frame((size, size), flip_x=fish.direction > 0)
            surface.blit(image, image.get_rect(center=(int(fish.x), int(fish.y))))
        self._draw_boat(surface, int(self.world.boat_x), 65, self.player.boat_level, 1.0)
        self._render_sea_hud(surface)

    def _render_sea_hud(self, surface: pygame.Surface) -> None:
        assert self.context is not None
        palette = ui.palette()
        self._game_chip(surface, self.return_button, "返航", active=True)
        reel_active = self.world.hooked is not None or self.reel_state != "idle"
        ui.button(surface, self.reel_button, "收线", active=reel_active)
        danger = bool(
            self.world.hooked
            and self.cargo_weight + self.world.hooked.weight > self.player.capacity
        )
        bar = pygame.Rect(302, 52, 100, 5)
        fill = min(1.0, self.cargo_weight / self.player.capacity)
        stats = pygame.Rect(294, 34, 118, 30)
        self._game_chip(surface, stats, "", active=False)
        pygame.draw.rect(surface, (210, 229, 235), bar, border_radius=3)
        width = int(bar.width * fill)
        if width:
            pygame.draw.rect(
                surface,
                palette.danger if danger else palette.warning,
                (bar.x, bar.y, width, bar.height),
                border_radius=3,
            )
        ui.text(
            surface,
            f"体{self.player.energy}  饵{self.bait_left}",
            (303, 38),
            12,
            (235, 246, 249),
            bold=True,
        )
        ui.glass_card(
            surface, pygame.Rect(416, 104, 28, 264), tint=palette.surface, radius=14, alpha=180
        )
        pygame.draw.line(surface, palette.accent_soft, (430, 116), (430, 356), 2)
        pygame.draw.circle(surface, palette.warning, (430, int(self.world.hook_target_depth)), 8)

    @staticmethod
    def _game_chip(surface: pygame.Surface, rect: pygame.Rect, label: str, *, active: bool) -> None:
        layer = pygame.Surface(rect.size, pygame.SRCALPHA)
        fill = (13, 59, 78, 218) if active else (8, 43, 60, 172)
        pygame.draw.rect(layer, fill, layer.get_rect(), border_radius=14)
        surface.blit(layer, rect)
        if label:
            ui.text(surface, label, rect.center, 15, (240, 248, 250), bold=True, center=True)

    def _render_decor(self, surface: pygame.Surface) -> None:
        pygame.draw.polygon(
            surface,
            (117, 99, 66),
            [(0, 442), (100, 430), (210, 443), (330, 427), (480, 440), (480, 480), (0, 480)],
        )
        for x, phase, height in ((35, 0.0, 52), (75, 1.2, 37), (375, 2.1, 47), (450, 0.7, 58)):
            sway = math.sin(self.elapsed * 1.5 + phase) * 7
            pygame.draw.line(surface, (40, 143, 105), (x, 455), (int(x + sway), 455 - height), 7)
        self._render_aquatic_props(surface)
        for index in range(11):
            y = 115 + (index * 29 - self.elapsed * (9 + index % 3)) % 260
            bubble_x = 20 + (index * 47) % 430 + math.sin(self.elapsed + index) * 4
            pygame.draw.circle(surface, (106, 184, 202), (int(bubble_x), int(y)), 3 + index % 4, 1)

    def _render_aquatic_props(self, surface: pygame.Surface) -> None:
        if not hasattr(self, "_aquatic_props"):
            props: dict[str, pygame.Surface] = {}
            for name in ("flora_1", "flora_4", "seaweed_1", "seaweed_3", "bush_1", "porcupine"):
                try:
                    asset = files("deskcamdio.assets.aquatic").joinpath(f"{name}.png")
                    with asset.open("rb") as stream:
                        props[name] = pygame.image.load(stream).convert_alpha()
                except (FileNotFoundError, ModuleNotFoundError, pygame.error):
                    continue
            self._aquatic_props = props
        placements = (
            ("flora_1", 112, 422, 2.0, 0.2),
            ("seaweed_3", 156, 429, 2.1, 1.1),
            ("bush_1", 305, 429, 2.2, 2.0),
            ("flora_4", 349, 415, 2.0, 0.6),
            ("porcupine", 410, 432, 1.35, 0.0),
        )
        for name, x, y, scale, phase in placements:
            image = self._aquatic_props.get(name)
            if image is None:
                continue
            key = (name, scale)
            frame = self._fishing_prop_frames.get(key)
            if frame is None:
                size = (
                    max(1, int(image.get_width() * scale)),
                    max(1, int(image.get_height() * scale)),
                )
                frame = pygame.transform.scale(image, size)
                self._fishing_prop_frames[key] = frame
            sway = int(
                math.sin(self.elapsed * 1.25 + phase)
                * (2 if "flora" in name or "weed" in name else 0)
            )
            surface.blit(frame, frame.get_rect(midbottom=(x + sway, y)))

    def _warehouse_fish(self, item: dict[str, int | str]) -> pygame.Surface:
        name = str(item.get("name") or "未知鱼")
        size_name = str(item.get("size") or "small")
        key = (name, size_name)
        cached = self._warehouse_fish_frames.get(key)
        if cached is not None:
            return cached
        color = sum(ord(character) for character in name) % 12
        animator = SpriteSheetAnimator.fish(color)
        animator.set_clip("idle")
        pixels = {"small": 35, "medium": 42, "large": 48}.get(size_name, 38)
        cached = animator.frame((pixels, pixels))
        self._warehouse_fish_frames[key] = cached
        return cached

    @staticmethod
    def _draw_coin(surface: pygame.Surface, center: tuple[int, int], radius: int) -> None:
        pygame.draw.circle(surface, (178, 111, 22), (center[0] + 1, center[1] + 2), radius)
        pygame.draw.circle(surface, (255, 194, 54), center, radius)
        pygame.draw.circle(surface, (255, 228, 119), center, max(2, radius - 3), 2)
        pygame.draw.line(
            surface,
            (190, 119, 24),
            (center[0], center[1] - radius // 2),
            (center[0], center[1] + radius // 2),
            max(1, radius // 4),
        )

    def _draw_boat(self, surface: pygame.Surface, x: int, y: int, level: int, scale: float) -> None:
        width = int((72 + (level - 1) * 11) * scale)
        height = int(25 * scale)
        hull = [
            (x - width // 2, y - height),
            (x + width // 2, y - height),
            (x + width // 3, y),
            (x - width // 3, y),
        ]
        pygame.draw.polygon(surface, (179, 88, 55), hull)
        pygame.draw.line(surface, (242, 183, 95), hull[0], hull[1], max(2, int(4 * scale)))
        cabin = pygame.Rect(
            x - int(18 * scale), y - int(42 * scale), int(33 * scale), int(18 * scale)
        )
        pygame.draw.rect(surface, (232, 218, 174), cabin)
        pygame.draw.rect(
            surface,
            (58, 122, 145),
            (cabin.x + 4, cabin.y + 4, max(4, cabin.w // 3), max(4, cabin.h // 2)),
        )
        if level >= 2:
            pygame.draw.rect(
                surface, (55, 62, 68), (x - width // 2 - 5, y - height, 8, int(18 * scale))
            )
        if level >= 3:
            pygame.draw.rect(
                surface,
                (210, 137, 68),
                (x + int(16 * scale), y - int(38 * scale), int(20 * scale), int(12 * scale)),
            )

    async def leave(self, reason: LeaveReason) -> None:
        del reason
        if self._save_task is not None:
            await self._save_task
        await self._flush_save()
        self.deactivate()

    async def dispose(self) -> None:
        if self._save_task is not None:
            await self._save_task
        await self._flush_save()
        self.deactivate()
        self.animators.clear()
        self.context = None
