"""Legacy fishing game coverage: trip, catch, capsize, shop and rendering."""

from __future__ import annotations

import pygame

from deskcamdio.apps.fishing.app import GameModal
from deskcamdio.apps.fishing.world import ReelResult


async def test_trip_and_catch_adds_cargo(harness) -> None:
    fishing = await harness.open("fishing")
    fishing.player.energy = 5
    fishing.bait_left = 5
    fishing._start_trip()
    assert fishing.at_sea is True

    before = len(fishing.cargo)
    fishing._complete_catch(ReelResult("caught", weight=2, value=20, size="small"))
    assert len(fishing.cargo) == before + 1
    assert fishing.cargo[-1]["weight"] == 2


async def test_capsize_returns_to_dock_and_charges_rescue(harness) -> None:
    fishing = await harness.open("fishing")
    fishing.player.coins = 200
    fishing.at_sea = True
    fishing.cargo = [{"name": "大鱼", "size": "large", "weight": 6, "value": 80}]
    fishing._complete_catch(ReelResult("caught", weight=6, value=120, size="large"))

    assert fishing.at_sea is False
    assert fishing.cargo == []
    assert fishing.bait_left == 0
    assert fishing.player.coins == 100
    assert fishing.modal is not None and "船翻" in fishing.modal.title


async def test_shop_buy_rejected_without_coins_then_rescue(harness) -> None:
    fishing = await harness.open("fishing")
    fishing.player.coins = 10
    fishing.bait_left = 0
    fishing.warehouse.clear()
    fishing._buy_bait()
    assert fishing.bait_left == 5

    fishing.player.coins = 10
    fishing.bait_left = 1
    fishing._buy_bait()
    assert fishing.bait_left == 1
    assert fishing.modal is not None and "金币不足" in fishing.modal.title


async def test_render_dock_sea_and_modal(harness) -> None:
    surface = pygame.Surface((480, 480))
    fishing = await harness.open("fishing")
    fishing.render(surface)
    fishing.at_sea = True
    fishing.modal = GameModal("提示", "测试旧版弹窗自动换行", 1.0, (40, 170, 110))
    fishing.render(surface)
    assert surface.get_bounding_rect().width == 480


async def test_legacy_state_persists_across_unmount(harness) -> None:
    fishing = await harness.open("fishing")
    fishing.player.coins = 321
    fishing.bait_left = 9
    fishing._save()
    await fishing._flush_save()
    await harness.manager.leave_current()

    restored = await harness.open("fishing")
    assert restored.player.coins == 321
    assert restored.bait_left == 9
