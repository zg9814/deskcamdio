"""Gallery: date-grouped thumbnails, disk cache, viewer with current±1."""

from __future__ import annotations

import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any

import pygame

from deskcamdio.core.lifecycle import App, LeaveReason, RouteState
from deskcamdio.core.runtime import RuntimeContext
from deskcamdio.ui import components
from deskcamdio.ui.animation import FishAnimator
from deskcamdio.ui.aquarium import ambient, seabed
from deskcamdio.ui.themes import ThemeTokens
from deskcamdio.ui.typography import draw_wrapped, render_text

THUMB_SIZE = 96
MEM_CACHE_LIMIT = 32
THUMB_DIR = "media/thumbnails"


class ThumbnailCache:
    """Single decode worker + bounded memory LRU + on-disk thumbs."""

    def __init__(self) -> None:
        self._memory: OrderedDict[Path, pygame.Surface] = OrderedDict()
        self._lock = threading.Lock()
        self._inflight: set[Path] = set()
        self._inflight_lock = threading.Lock()

    def thumb_path(self, source: Path, data_dir: Path) -> Path:
        directory = data_dir / THUMB_DIR
        directory.mkdir(parents=True, exist_ok=True)
        return directory / f"{source.stem}-{source.stat().st_mtime_ns % 10**9}.jpg"

    def get(self, source: Path, data_dir: Path, scope: Any | None = None) -> pygame.Surface | None:
        cached = self._memory.get(source)
        if cached is not None:
            self._memory.move_to_end(source)
            return cached
        disk = self.thumb_path(source, data_dir)
        if disk.exists():
            try:
                surface = pygame.image.load(str(disk))
                self._store(source, surface)
                return surface
            except pygame.error:
                pass
        # Single-flight: render() runs every frame; without this guard a slow
        # decode would spawn one thread per tile per frame.
        with self._inflight_lock:
            if source in self._inflight:
                return None
            self._inflight.add(source)
        try:
            if scope is not None:
                scope.run_in_thread(lambda: self._decode(source, data_dir), name="gallery-thumb")
            else:
                threading.Thread(
                    target=self._decode,
                    args=(source, data_dir),
                    daemon=True,
                    name="gallery-thumb",
                ).start()
        except BaseException:
            self._release(source)
            raise
        return None

    def _release(self, source: Path) -> None:
        with self._inflight_lock:
            self._inflight.discard(source)

    def _store(self, source: Path, surface: pygame.Surface) -> None:
        with self._lock:
            self._memory[source] = surface
            while len(self._memory) > MEM_CACHE_LIMIT:
                self._memory.popitem(last=False)

    def _decode(self, source: Path, data_dir: Path) -> None:
        try:
            disk = self.thumb_path(source, data_dir)
            image = pygame.image.load(str(source))
            scaled = pygame.transform.smoothscale(image, (THUMB_SIZE, THUMB_SIZE))
            pygame.image.save(scaled, str(disk))
            self._store(source, scaled)
        except Exception:  # noqa: BLE001 - corrupt file just shows placeholder
            pass
        finally:
            self._release(source)


class GalleryApp(App):
    def __init__(self) -> None:
        self._context: RuntimeContext | None = None
        self._unsub_photo_created: Any = None
        self.cache = ThumbnailCache()
        self.photos: list[Path] = []
        self.viewer_index: int | None = None
        self._viewer_surfaces: dict[int, pygame.Surface | None] = {}
        self._tiles: list[tuple[Path, pygame.Rect]] = []
        self._empty_fish = FishAnimator(3)
        self._empty_fish_x = 176.0
        self._empty_fish_direction = 1
        self._elapsed = 0.0

    async def mount(self, context: RuntimeContext) -> None:
        self._context = context
        self._unsub_photo_created = context.bus.subscribe(
            "photo.created", lambda _event: self.refresh()
        )
        if getattr(context, "scope", None) is not None:
            context.scope.track_subscription(
                self._unsub_photo_created, name="gallery:photo-created"
            )  # noqa: E501
        self.refresh()

    def refresh(self) -> None:
        context = self._context
        if context is None:
            return
        photos = sorted((context.data_dir / "media" / "photos").glob("*.jpg"), reverse=True)
        self.photos = [p for p in photos if not p.name.endswith(".part")]

    async def enter(self, route: RouteState) -> None:
        self.viewer_index = None
        self._viewer_surfaces.clear()
        self.refresh()

    def handle_input(self, event: pygame.event.Event) -> None:
        if event.type != pygame.MOUSEBUTTONDOWN:
            return
        if self.viewer_index is not None:
            self.viewer_index = None
            return
        for index, (_path, rect) in enumerate(self._tiles):
            if rect.collidepoint(event.pos):
                self.viewer_index = index
                self._viewer_surfaces.clear()
                break

    def update(self, delta_seconds: float) -> None:
        self._elapsed += delta_seconds
        if not self.photos:
            self._empty_fish.update(delta_seconds)
            self._empty_fish_x += 18 * self._empty_fish_direction * delta_seconds
            if self._empty_fish_x >= 280:
                self._empty_fish_direction = -1
            elif self._empty_fish_x <= 136:
                self._empty_fish_direction = 1

    def render(self, surface: pygame.Surface) -> None:
        assert self._context is not None
        theme = self._context.theme.tokens
        ambient(surface, theme, self._elapsed * 0.4)
        context = self._context
        if context is None:
            return
        if self.viewer_index is not None:
            self._render_viewer(surface, theme)
            return
        header = render_text(f"相册 · {len(self.photos)} 张", 20, theme.text_primary, bold=True)
        surface.blit(header, (16, 12))
        self._tiles.clear()
        columns = 4
        for index, photo in enumerate(self.photos[:32]):
            rect = pygame.Rect(0, 0, THUMB_SIZE, THUMB_SIZE)
            rect.topleft = (16 + (index % columns) * 112, 56 + (index // columns) * 112)
            thumb = self.cache.get(photo, context.data_dir, scope=context.scope)
            if thumb is not None:
                surface.blit(pygame.transform.smoothscale(thumb, rect.size), rect.topleft)
            else:
                pygame.draw.rect(surface, theme.surface, rect, border_radius=10)
            self._tiles.append((photo, rect))
        if not self.photos:
            seabed(surface, theme, self._elapsed * 0.3)
            components.glass_card(surface, pygame.Rect(48, 92, 384, 224), theme, alpha=205)
            fish = self._empty_fish.frame((76, 76), flip_x=self._empty_fish_direction < 0)
            surface.blit(fish, fish.get_rect(center=(round(self._empty_fish_x), 266)))
            components.icon(surface, "photo", (240, 145), 36, theme.accent)
            hint = render_text("还没有照片", 20, theme.text_primary, bold=True)
            surface.blit(hint, hint.get_rect(center=(240, 190)))
            sub = render_text("打开相机，记录第一张水下记忆", 15, theme.text_secondary)
            surface.blit(sub, sub.get_rect(center=(240, 220)))

    def _render_viewer(self, surface: pygame.Surface, theme: ThemeTokens) -> None:
        assert self.viewer_index is not None and self._context is not None
        current = self.photos[self.viewer_index]
        key = self.viewer_index
        if key not in self._viewer_surfaces:
            try:
                loaded = pygame.image.load(str(current))
                self._viewer_surfaces[key] = pygame.transform.smoothscale(loaded, (480, 400))
            except pygame.error:
                self._viewer_surfaces[key] = None
        image = self._viewer_surfaces.get(key)
        if image is not None:
            surface.blit(image, (0, 40))
        else:
            pygame.draw.rect(surface, theme.surface, pygame.Rect(0, 40, 480, 400))
        draw_wrapped(
            surface,
            current.name,
            pygame.Rect(12, 446, 456, 32),
            14,
            theme.text_secondary,
            line_gap=1,
        )
        # Keep only current ± 1 decoded.
        keep = {key - 1, key, key + 1}
        for stale in [k for k in self._viewer_surfaces if k not in keep]:
            del self._viewer_surfaces[stale]

    async def leave(self, reason: LeaveReason) -> None:
        self._viewer_surfaces.clear()

    async def dispose(self) -> None:
        if self._unsub_photo_created is not None:
            self._unsub_photo_created()  # idempotent; also tracked by scope
            self._unsub_photo_created = None
        self._context = None
        self.photos.clear()
        with self.cache._lock:  # noqa: SLF001 - owner-internal reset
            self.cache._memory.clear()
