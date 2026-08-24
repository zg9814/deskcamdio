"""Fishing app branch coverage: landing, capsize, shop close, modal render."""

from __future__ import annotations

import pygame

from deskcamdio.apps.fishing.world import HookState


async def test_land_fish_adds_cargo_and_spends_energy(harness) -> None:
    fishing = await harness.open("fishing")
    fishing.player.energy = 5
    fishing.player.coins = 100
    fishing.world.cast()
    fishing.world.update(10.0)
    assert fishing.world.hook_state is HookState.FIGHTING
    fishing.world.progress = 0.99
    fishing.world.reel()
    assert fishing.world.hook_state is HookState.LANDED

    cargo_before = len(fishing.player.cargo)
    fishing._land_fish()
    assert len(fishing.player.cargo) == cargo_before + 1
    assert fishing.player.energy == 4
    assert fishing.world.hook_state is HookState.IDLE


async def test_capsize_clears_cargo_and_charges_rescue(harness) -> None:
    from deskcamdio.apps.fishing.economy import CAPSIZE_LOSS_COINS

    fishing = await harness.open("fishing")
    # Pre-load cargo beyond the limit; next landing capsizes the boat.
    fishing.player.cargo.append(
        {
            "species": "carp",
            "name": "鲤鱼",
            "weight": 40.0,
            "rare": False,
            "value": 10,
            "caught_at": 0,
        }
    )
    fishing.player.energy = 5
    fishing.player.coins = 200
    fishing.player.bait = 7

    fishing.world.cast()
    fishing.world.update(10.0)
    fishing.world.progress = 1.0
    fishing.world.reel()
    fishing._land_fish()

    assert fishing.player.cargo == []
    assert fishing.player.bait == 0
    assert fishing.player.coins == 200 - CAPSIZE_LOSS_COINS


async def test_shop_buy_rejected_without_coins_then_close(harness) -> None:
    fishing = await harness.open("fishing")
    fishing.modal = "shop"
    fishing.player.coins = 15  # cannot afford a pack (costs 100)
    fishing.handle_input(pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"pos": (160, 274)}))
    assert fishing.player.bait == 20  # purchase rejected, stock unchanged
    fishing.handle_input(
        pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"pos": (240, 350)})
    )  # close button
    assert fishing.modal is None


async def test_render_modal_and_qte_branches(harness) -> None:
    surface = pygame.Surface((480, 480))
    fishing = await harness.open("fishing")
    fishing.modal = "shop"
    fishing.world.cast()
    fishing.world.update(10.0)
    if fishing.world.current is not None:
        fishing.world.current["rare"] = True
    fishing.world.qte_active = True
    fishing.render(surface)
    fishing.modal = None
    fishing.render(surface)
