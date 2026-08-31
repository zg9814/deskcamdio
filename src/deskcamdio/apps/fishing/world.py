from __future__ import annotations

import math
import random
from dataclasses import dataclass

from deskcamdio.apps.fishing.economy import PlayerState

FISH_NAMES = {
    1: "一二鱼",
    2: "响响鱼",
    3: "小七鱼",
    4: "小七鱼",
    6: "大志鱼",
    7: "大志鱼",
    8: "锅新鱼",
    9: "锅新鱼",
}


def fish_name(weight: int) -> str:
    return FISH_NAMES.get(weight, "小七鱼")


@dataclass(slots=True)
class Fish:
    fish_id: int
    x: float
    y: float
    direction: int
    speed: float
    size: str
    weight: int
    value: int
    color: int
    state: str = "swim"
    bite_deadline: float = 0.0
    next_escape_check: float = 0.0
    check_in: float = 0.0

    @property
    def radius(self) -> int:
        return {"small": 18, "medium": 25, "large": 35}[self.size]


@dataclass(frozen=True, slots=True)
class ReelResult:
    status: str
    weight: int = 0
    value: int = 0
    size: str = ""

    @property
    def name(self) -> str:
        return fish_name(self.weight)


class FishingWorld:
    def __init__(self, rng: random.Random | None = None, fish_count: int | None = None) -> None:
        self.rng = rng or random.Random()
        self.time = 0.0
        self.boat_x = 240.0
        self.boat_target_x = 240.0
        self.hook_depth = 230.0
        self.hook_target_depth = 230.0
        self.next_id = 1
        self.events: list[str] = []
        count = fish_count if fish_count is not None else self.rng.randint(8, 12)
        self.fish = [self._spawn() for _ in range(count)]

    def _spawn(self) -> Fish:
        roll = self.rng.random()
        size = "small" if roll < 0.58 else "medium" if roll < 0.88 else "large"
        ranges = {
            "small": ((1, 2), (10, 25), (33.0, 53.0)),
            "medium": ((3, 4), (40, 80), (42.0, 65.0)),
            "large": ((6, 9), (120, 250), (24.0, 40.0)),
        }
        weight_range, value_range, speed_range = ranges[size]
        fish = Fish(
            fish_id=self.next_id,
            x=self.rng.uniform(30, 450),
            y=self.rng.uniform(145, 355),
            direction=self.rng.choice((-1, 1)),
            speed=self.rng.uniform(*speed_range),
            size=size,
            weight=self.rng.randint(*weight_range),
            value=self.rng.randint(*value_range),
            color=self.rng.randrange(12),
            check_in=self.rng.random(),
        )
        self.next_id += 1
        return fish

    @property
    def hooked(self) -> Fish | None:
        return next((fish for fish in self.fish if fish.state in {"bite", "reeling"}), None)

    def set_boat_target(self, x: float) -> None:
        self.boat_target_x = min(430.0, max(50.0, x))

    def set_hook_target(self, y: float) -> None:
        self.hook_target_depth = min(362.0, max(125.0, y))

    def update(  # noqa: C901 - preserved legacy fish simulation
        self,
        delta: float,
        player: PlayerState,
        *,
        can_bite: bool = True,
        hook_speed: float = 160.0,
    ) -> None:
        self.time += delta
        boat_delta = self.boat_target_x - self.boat_x
        self.boat_x += max(-player.boat_speed * delta, min(player.boat_speed * delta, boat_delta))
        hook_delta = self.hook_target_depth - self.hook_depth
        self.hook_depth += max(-hook_speed * delta, min(hook_speed * delta, hook_delta))
        active_bite = self.hooked
        for fish in self.fish:
            if fish.state in {"bite", "reeling"}:
                fish.x += (self.boat_x - fish.x) * min(1.0, delta * 5)
                fish.y += (self.hook_depth - fish.y) * min(1.0, delta * 5)
                if fish.state == "bite" and self.time > fish.bite_deadline:
                    fish.state = "flee"
                    fish.direction = -1 if fish.x < 240 else 1
                    self.events.append("bite_timeout")
                elif fish.state == "reeling" and self.time >= fish.next_escape_check:
                    fish.next_escape_check += 2.0
                    size_factor = {"small": 0.35, "medium": 0.65, "large": 1.0}[fish.size]
                    survive_chance = 1.0 - (1.0 - player.hook_chance) * size_factor
                    if self.rng.random() >= survive_chance:
                        fish.state = "flee"
                        fish.direction = -1 if fish.x < 240 else 1
                        self.events.append("reel_escaped")
                continue
            multiplier = 2.4 if fish.state == "flee" else 1.0
            fish.x += fish.direction * fish.speed * multiplier * delta
            if fish.x < -fish.radius:
                fish.x = 480 + fish.radius
                fish.state = "swim"
            elif fish.x > 480 + fish.radius:
                fish.x = -fish.radius
                fish.state = "swim"
            fish.check_in -= delta
            distance = math.hypot(fish.x - self.boat_x, fish.y - self.hook_depth)
            if (
                can_bite
                and fish.state == "swim"
                and active_bite is None
                and distance <= fish.radius + 18
            ):
                if fish.check_in <= 0:
                    fish.check_in = 1.0
                    size_factor = {"small": 1.0, "medium": 0.8, "large": 0.55}[fish.size]
                    if self.rng.random() < player.bite_chance * size_factor:
                        fish.state = "bite"
                        fish.bite_deadline = self.time + player.bite_window
                        active_bite = fish
            elif distance > fish.radius + 24:
                fish.check_in = min(fish.check_in, 0.0)

    def begin_reel(self) -> ReelResult:
        fish = self.hooked
        if fish is None:
            return ReelResult("empty")
        if fish.state != "bite" or self.time > fish.bite_deadline:
            return ReelResult("empty")
        fish.state = "reeling"
        fish.next_escape_check = self.time + 2.0
        return ReelResult("started", fish.weight, fish.value, fish.size)

    def land_reeling(self) -> ReelResult:
        fish = next((item for item in self.fish if item.state == "reeling"), None)
        if fish is None:
            return ReelResult("empty")
        result = ReelResult("caught", fish.weight, fish.value, fish.size)
        self.fish.remove(fish)
        self.fish.append(self._spawn())
        return result

    def pop_events(self) -> list[str]:
        events, self.events = self.events, []
        return events

    def reset_bite_checks(self) -> None:
        """Allow nearby swimming fish to make a fresh bite check."""
        for fish in self.fish:
            if fish.state == "swim":
                fish.check_in = 0.0
