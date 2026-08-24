"""Fishing world simulation: bite, reel, escape, QTE rings."""

from __future__ import annotations

import random
import time

from deskcamdio.apps.fishing.economy import (
    QTE_WINDOW,
    RARE_CHANCE,
    SPECIES,
    day_period,
    fish_value,
    roll_species,
)


class HookState:
    IDLE = "idle"
    WAITING = "waiting"
    FIGHTING = "fighting"
    LANDED = "landed"
    ESCAPED = "escaped"


class World:
    def __init__(self) -> None:
        self.rng = random.Random()
        self.hook_state = HookState.IDLE
        self.current: dict | None = None
        self.progress = 0.0
        self.survival_bonus = 0.0
        self.qte_ring_radius = 0.0
        self.qte_active = False
        self._next_bite = 2.0
        self.period = day_period()

    def cast(self) -> None:
        if self.hook_state is not HookState.IDLE:
            return
        self.hook_state = HookState.WAITING
        self._next_bite = self.rng.uniform(1.5, 4.5)

    def update(self, delta: float) -> None:
        self.period = day_period()
        if self.hook_state is HookState.WAITING:
            self._next_bite -= delta
            if self._next_bite <= 0:
                self._spawn_fish()
                self.hook_state = HookState.FIGHTING
        elif self.hook_state is HookState.FIGHTING:
            assert self.current is not None
            fight = float(self.current["fight"]) * (1.0 - self.survival_bonus)
            self.progress -= fight * delta * 0.55
            if self.qte_active:
                self.qte_ring_radius += delta * 220.0
                if self.qte_ring_radius > 120.0:
                    self.qte_active = False
            else:
                if self.rng.random() < delta * 0.6:
                    self.qte_active = True
                    self.qte_ring_radius = 90.0
            if self.progress <= 0.0:
                self.hook_state = HookState.ESCAPED
                self.current = None

    def reel(self) -> str:
        """Returns '', 'qte-hit', or 'qte-early'."""
        result = ""
        if self.qte_active and self.qte_ring_radius <= QTE_WINDOW * 220.0 + 18.0:
            self.survival_bonus = min(0.9, self.survival_bonus + 0.25)
            self.qte_active = False
            result = "qte-hit"
        elif self.qte_active:
            self.survival_bonus = max(0.0, self.survival_bonus - 0.15)
            self.qte_active = False
            result = "qte-early"
        if self.hook_state is HookState.FIGHTING:
            self.progress += 0.34
            assert self.current is not None
            if self.progress >= 1.0:
                self.progress = 1.0
                self.hook_state = HookState.LANDED
        return result

    def _spawn_fish(self) -> None:
        species = roll_species(self.period, self.rng)
        rare = self.rng.random() < RARE_CHANCE
        low, high = SPECIES[species]["weight"]
        weight = round(self.rng.uniform(low, high), 2)
        self.current = {
            "species": species,
            "name": SPECIES[species]["name"],
            "weight": weight,
            "rare": rare,
            "value": fish_value(species, weight, rare, self.period),
            "fight": min(1.4, SPECIES[species]["fight"] * (0.7 + weight / high)),
            "caught_at": time.time(),
        }
        self.progress = 0.25
        self.survival_bonus = 0.0
