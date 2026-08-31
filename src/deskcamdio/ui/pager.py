"""Frame-driven, touch-friendly horizontal page transitions."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from math import copysign, exp


def _ease_out_quint(value: float) -> float:
    """Fast response followed by a long, soft settle."""
    value = max(0.0, min(1.0, value))
    return 1.0 - (1.0 - value) ** 5


@dataclass(slots=True)
class _Tween:
    value: float = 0.0
    start_value: float = 0.0
    end_value: float = 0.0
    duration: float = 0.0
    elapsed: float = 0.0
    active: bool = False

    def start(self, beginning: float, end: float, duration: float = 0.26) -> None:
        self.value = beginning
        self.start_value = beginning
        self.end_value = end
        self.duration = max(0.001, duration)
        self.elapsed = 0.0
        self.active = True

    def snap(self, value: float) -> None:
        self.value = value
        self.active = False

    def update(self, delta_seconds: float) -> float:
        if not self.active:
            return self.value
        self.elapsed += max(0.0, delta_seconds)
        progress = min(1.0, self.elapsed / self.duration)
        eased = _ease_out_quint(progress)
        self.value = self.start_value + (self.end_value - self.start_value) * eased
        if progress >= 1.0:
            self.value = self.end_value
            self.active = False
        return self.value


@dataclass(slots=True)
class PagePager:
    """Tracks drag offset and animates page changes without blocking the UI."""

    page_count: int
    width: int = 480
    index: int = 0
    offset: float = 0.0
    _start_x: float = 0.0
    _last_x: float = 0.0
    _last_at: float = 0.0
    _velocity: float = 0.0
    _dragging: bool = False
    _target_index: int | None = None
    _motion: _Tween = field(default_factory=_Tween)

    def __post_init__(self) -> None:
        self.set_page_count(self.page_count)

    @property
    def is_animating(self) -> bool:
        return self._motion.active

    @property
    def is_dragging(self) -> bool:
        return self._dragging

    def set_page_count(self, count: int) -> None:
        self.page_count = max(1, int(count))
        self.index = max(0, min(self.index, self.page_count - 1))
        if not self.is_animating:
            self.offset = 0.0

    def set_index(self, index: int) -> None:
        self.index = max(0, min(int(index), self.page_count - 1))
        self._target_index = None
        self.offset = 0.0
        self._motion.snap(0.0)

    def begin_drag(self, x: float, now: float | None = None) -> None:
        if self.is_animating:
            return
        self._start_x = self._last_x = x
        self._last_at = now if now is not None else time.monotonic()
        self._velocity = 0.0
        self._dragging = False

    def drag_to(self, x: float, now: float | None = None) -> None:
        if self.is_animating:
            return
        at = now if now is not None else time.monotonic()
        elapsed = at - self._last_at
        delta = x - self._last_x
        if elapsed > 0 and abs(delta) >= 1.0:
            instantaneous = delta / elapsed
            self._velocity = self._velocity * 0.35 + instantaneous * 0.65
        raw = x - self._start_x
        if (self.index == 0 and raw > 0) or (self.index == self.page_count - 1 and raw < 0):
            limit = self.width * 0.28
            raw = copysign(limit * (1.0 - exp(-abs(raw) * 0.34 / limit)), raw)
        self.offset = raw
        self._dragging = self._dragging or abs(raw) >= 8
        self._last_x = x
        self._last_at = at

    def end_drag(self, x: float, now: float | None = None) -> bool:
        if self.is_animating:
            return True
        released_at = now if now is not None else time.monotonic()
        self.drag_to(x, released_at)
        target = self.index
        if self.offset <= -self.width * 0.18 or self._velocity <= -720:
            target += 1
        elif self.offset >= self.width * 0.18 or self._velocity >= 720:
            target -= 1
        target = max(0, min(self.page_count - 1, target))
        dragged = self._dragging
        self._dragging = False
        if target == self.index and abs(self.offset) < 0.5:
            self._target_index = None
            self.offset = 0.0
            self._motion.snap(0.0)
            return dragged
        self._target_index = target
        destination = -(target - self.index) * self.width
        distance_ratio = min(1.0, abs(destination - self.offset) / self.width)
        velocity_bonus = min(0.07, abs(self._velocity) / 12000.0)
        duration = max(0.18, 0.22 + 0.12 * distance_ratio - velocity_bonus)
        self._motion.start(self.offset, destination, duration)
        return dragged

    def move(self, delta: int) -> bool:
        if self.is_animating:
            return False
        target = max(0, min(self.page_count - 1, self.index + int(delta)))
        if target == self.index:
            return False
        self._target_index = target
        self._motion.start(self.offset, -(target - self.index) * self.width, 0.32)
        return True

    def update(self, delta_seconds: float) -> None:
        if not self.is_animating:
            return
        self.offset = self._motion.update(delta_seconds)
        if not self.is_animating:
            if self._target_index is not None:
                self.index = self._target_index
            self._target_index = None
            self.offset = 0.0

    def page_x(self, page_index: int) -> int:
        return int((page_index - self.index) * self.width + self.offset)

    def visible_pages(self) -> tuple[int, ...]:
        pages = {self.index}
        if self.offset < 0 and self.index + 1 < self.page_count:
            pages.add(self.index + 1)
        elif self.offset > 0 and self.index > 0:
            pages.add(self.index - 1)
        if self._target_index is not None:
            pages.add(self._target_index)
        return tuple(sorted(pages))
