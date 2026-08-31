from __future__ import annotations

from dataclasses import dataclass

MAX_ENERGY = 100
ENERGY_RECOVERY_SECONDS = 300
UPGRADE_COSTS = {"boat": (200, 700), "rod": (150, 500), "bait": (100, 350)}
BOAT_CAPACITY = (6, 10, 15)
BOAT_SPEED = (70.0, 90.0, 115.0)
ROD_CHANCE = (0.55, 0.70, 0.85)
ROD_WINDOW = (1.5, 1.8, 2.1)
BAIT_CHANCE = (0.25, 0.38, 0.52)


@dataclass(slots=True)
class PlayerState:
    coins: int = 0
    boat_level: int = 1
    rod_level: int = 1
    bait_level: int = 1
    energy: int = MAX_ENERGY
    last_energy_at: float = 0.0

    @property
    def capacity(self) -> int:
        return BOAT_CAPACITY[self.boat_level - 1]

    @property
    def boat_speed(self) -> float:
        return BOAT_SPEED[self.boat_level - 1]

    @property
    def hook_chance(self) -> float:
        return ROD_CHANCE[self.rod_level - 1]

    @property
    def bite_window(self) -> float:
        return ROD_WINDOW[self.rod_level - 1]

    @property
    def bite_chance(self) -> float:
        return BAIT_CHANCE[self.bait_level - 1]

    def recover_energy(self, now: float) -> int:
        if self.last_energy_at <= 0:
            self.last_energy_at = now
            return 0
        elapsed = max(0.0, now - self.last_energy_at)
        recovered = min(MAX_ENERGY - self.energy, int(elapsed // ENERGY_RECOVERY_SECONDS))
        if recovered:
            self.energy += recovered
            self.last_energy_at += recovered * ENERGY_RECOVERY_SECONDS
        elif self.energy >= MAX_ENERGY:
            self.last_energy_at = now
        return recovered

    def upgrade(self, kind: str) -> bool:
        attribute = f"{kind}_level"
        level = int(getattr(self, attribute))
        if kind not in UPGRADE_COSTS or level >= 3:
            return False
        cost = UPGRADE_COSTS[kind][level - 1]
        if self.coins < cost:
            return False
        self.coins -= cost
        setattr(self, attribute, level + 1)
        return True

    def reset_equipment(self) -> None:
        self.boat_level = self.rod_level = self.bait_level = 1
