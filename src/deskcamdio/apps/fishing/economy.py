"""Fishing economy constants and player state (guide §10 钓鱼)."""

from __future__ import annotations

import json
import random
import time
from dataclasses import asdict, dataclass, field
from typing import Any

SPECIES: dict[str, dict[str, Any]] = {
    "carp": {"name": "鲤鱼", "base": 12, "weight": (0.4, 3.0), "fight": 0.35},
    "trout": {"name": "鳟鱼", "base": 18, "weight": (0.3, 2.2), "fight": 0.5},
    "catfish": {"name": "鲇鱼", "base": 26, "weight": (0.8, 6.0), "fight": 0.7},
    "koi": {"name": "锦鲤", "base": 60, "weight": (0.5, 4.0), "fight": 0.85},
    "eel": {"name": "河鳗", "base": 44, "weight": (0.4, 2.8), "fight": 0.95},
}
RARE_CHANCE = 0.02
RARE_VALUE_MULT = 5.0
QTE_WINDOW = 0.09
QTE_BONUS = 0.25
BAIT_PRICE = 20
BAIT_PACK = 5
RESCUE_BAIT = 5
RESCUE_COST = 100
CAPSIZE_LOSS_COINS = 100
CARGO_LIMIT_KG = 30.0

DAY_PERIODS = ((5, "dawn"), (11, "day"), (17, "dusk"), (21, "night"))


def day_period(now: float | None = None) -> str:
    hour = time.localtime(now if now is not None else time.time()).tm_hour
    current = DAY_PERIODS[-1][1]
    for start, name in DAY_PERIODS:
        if hour >= start:
            current = name
    return current


@dataclass
class PlayerState:
    coins: int = 50
    energy: int = 100
    bait: int = 20
    rod_level: int = 1
    cargo: list[dict] = field(default_factory=list)
    collection: dict[str, dict] = field(default_factory=dict)
    codex_reward_half: bool = False
    golden_boat: bool = False

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str) -> PlayerState:
        data = json.loads(raw)
        return cls(**data)

    def cargo_weight(self) -> float:
        return sum(item["weight"] for item in self.cargo)

    def sell_all(self) -> int:
        total = 0
        for item in self.cargo:
            value = int(item["value"])
            total += value
            key = f"{item['species']}:{item['rare']}"
            entry = self.collection.setdefault(
                key, {"species": item["species"], "count": 0, "first_at": time.time()}
            )
            entry["count"] += 1
        self.cargo.clear()
        self.coins += total
        return total


def fish_value(species: str, weight: float, rare: bool, period: str) -> int:
    base = SPECIES[species]["base"]
    multiplier = RARE_VALUE_MULT if rare else 1.0
    period_bonus = 1.15 if period == "night" else 1.05 if period == "dusk" else 1.0
    return max(1, int(base * weight * multiplier * period_bonus))


def roll_species(period: str, rng: random.Random) -> str:
    weights = {name: 1.0 for name in SPECIES}
    if period == "night":
        weights["eel"] *= 2.0
        weights["catfish"] *= 1.4
    elif period == "dawn":
        weights["trout"] *= 1.8
    elif period == "day":
        weights["carp"] *= 1.5
    total = sum(weights.values())
    pick = rng.random() * total
    acc = 0.0
    for name, weight in weights.items():
        acc += weight
        if pick <= acc:
            return name
    return "carp"


def bite_chance(energy: int, period: str) -> float:
    chance = 0.35
    if period == "dusk":
        chance += 0.10
    if energy < 30:
        chance -= 0.08
    return max(0.05, min(0.9, chance))
