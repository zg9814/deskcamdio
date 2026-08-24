"""Camera app: live preview loop, shutter, quality/filter selection."""

from __future__ import annotations

import asyncio
import io
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pygame

from deskcamdio.core.lifecycle import App, LeaveReason, RouteState
from deskcamdio.core.runtime import RuntimeContext
from deskcamdio.services.camera_client import BaseCameraClient, CameraUnavailable
from deskcamdio.ui import components
from deskcamdio.ui.aquarium import gradient
from deskcamdio.ui.typography import render_text

QUALITIES = {"low": "低", "medium": "中", "high": "高"}
FILTERS = ["原片", "CCD", "徕卡", "黑白"]
FILTER_KEYS = {1: "ccd", 2: "leica", 3: "bw"}
FILTER_WORKER = [sys.executable, "-m", "deskcamdio.cli.photo_worker"]
PREVIEW_INTERVAL = 1 / 8  # worker pushes ~8 fps


def photos_dir(context: RuntimeContext) -> Path:
    directory = context.data_dir / "media" / "photos"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


class CameraApp(App):
    def __init__(self) -> None:
        self._context: RuntimeContext | None = None
        self._camera: BaseCameraClient | None = None
        self._preview_surface: pygame.Surface | None = None
        self._quality = "medium"
        self._filter = 0
        self._buttons: dict[str, pygame.Rect] = {}
        self._busy = False
        self._error = ""
        self._preview_task: asyncio.Task[None] | None = None
        self._latest_thumbnail: pygame.Surface | None = None
        self._filter_open = False
        self._preview_rect = pygame.Rect(16, 76, 448, 276)
        self._thumbnail_rect = pygame.Rect(18, 374, 76, 62)
        self._quality_rect = pygame.Rect(104, 378, 90, 52)
        self._shutter_rect = pygame.Rect(204, 368, 72, 72)
        self._filter_rect = pygame.Rect(364, 378, 98, 52)
        self._style_rects = tuple(
            pygame.Rect(28 + index * 106, 300, 98, 48) for index in range(len(FILTERS))
        )

    def _spawn(self, coro: Any, *, name: str | None = None) -> Any:
        """Schedule work on this app's TaskScope; returns the Task."""
        import asyncio

        ctx = self._context
        scope = getattr(ctx, "scope", None) if ctx is not None else None
        if scope is not None:
            return scope.create_task(coro, name=name)
        return asyncio.get_running_loop().create_task(coro, name=name)

    async def mount(self, context: RuntimeContext) -> None:
        from deskcamdio.platform import create_camera_client

        self._context = context
        self._camera = create_camera_client(context.effective_run_dir)

    async def enter(self, route: RouteState) -> None:
        assert self._context is not None
        self._error = ""
        if self._camera is not None and not await self._camera.ensure_running():
            self._error = "未检测到 IMX708，可返回"
            return
        latest = max(
            photos_dir(self._context).glob("*.jpg"),
            key=lambda p: p.stat().st_mtime_ns,
            default=None,
        )
        self._start_preview_loop()
        if latest is not None:
            self._spawn(self._load_thumbnail(latest), name="camera:latest-thumbnail")

    def _start_preview_loop(self) -> None:
        if self._preview_task is None or self._preview_task.done():
            self._preview_task = self._spawn(self._preview_loop(), name="camera:preview")

    async def _preview_loop(self) -> None:
        assert self._camera is not None
        while True:
            try:
                jpeg = await asyncio.wait_for(self._camera.preview_async(), timeout=2.0)
                if jpeg:
                    surface = pygame.image.load(io.BytesIO(jpeg))
                    self._preview_surface = pygame.transform.smoothscale(surface, (480, 360))
            except TimeoutError:
                pass
            except Exception:  # noqa: BLE001 - preview hiccups must not kill the page
                self._preview_surface = None
            await asyncio.sleep(PREVIEW_INTERVAL)

    def handle_input(self, event: pygame.event.Event) -> None:
        context = self._context
        if context is None or event.type != pygame.MOUSEBUTTONDOWN or self._busy:
            return
        if self._filter_open:
            selected = next(
                (
                    index
                    for index, rect in enumerate(self._style_rects)
                    if rect.collidepoint(event.pos)
                ),
                None,
            )
            if selected is not None:
                self._filter = selected
            self._filter_open = False
            return
        hit_key = next(
            (key for key, rect in self._buttons.items() if rect.collidepoint(event.pos)),
            None,
        )
        if hit_key == "shutter":
            self._spawn(self._capture())
        elif (
            hit_key == "thumbnail"
            and self._latest_thumbnail is not None
            and context.launch is not None
        ):
            context.launch("gallery")
        elif hit_key == "quality":
            qualities = tuple(QUALITIES)
            self._quality = qualities[(qualities.index(self._quality) + 1) % len(qualities)]
        elif hit_key == "filter":
            self._filter_open = True

    async def _capture(self) -> None:
        context = self._context
        camera = self._camera
        if context is None or camera is None:
            return
        self._busy = True
        try:
            stamp = time.strftime("%Y%m%d-%H%M%S")
            destination = photos_dir(context) / f"IMG-{stamp}-{time.monotonic_ns() % 1000:03d}.jpg"
            await camera.capture(self._quality, destination)
            if self._filter > 0:
                await self._apply_filter(destination)
            context.bus.publish("photo.created", path=str(destination))
            context.audio.play_sound("shutter", category="shutter")
            self._spawn(self._load_thumbnail(destination), name="camera:latest-thumbnail")
        except CameraUnavailable as exc:
            self._error = str(exc)
        finally:
            self._busy = False

    async def _apply_filter(self, destination: Path) -> None:
        name = FILTER_KEYS[self._filter]
        process = await asyncio.create_subprocess_exec(
            *FILTER_WORKER,
            "--src",
            str(destination),
            "--dst",
            str(destination),
            "--filter",
            name,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            await asyncio.wait_for(process.wait(), timeout=30.0)
        except asyncio.CancelledError:
            process.kill()
            await process.wait()
            raise
        except TimeoutError:
            process.kill()
            await process.wait()

    async def _load_thumbnail(self, source: Path) -> None:
        assert self._context is not None
        target = self._context.data_dir / "media" / "thumbnails" / "latest-camera.jpg"
        process = await asyncio.create_subprocess_exec(
            *FILTER_WORKER,
            "--src",
            str(source),
            "--dst",
            str(target),
            "--thumbnail",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            exit_code = await process.wait()
        except asyncio.CancelledError:
            process.kill()
            await process.wait()
            raise
        if exit_code == 0 and target.exists():
            with target.open("rb") as handle:
                loaded = pygame.image.load(handle, target.name)
                self._latest_thumbnail = (
                    loaded.convert() if pygame.display.get_surface() else loaded
                )

    def update(self, delta_seconds: float) -> None:
        del delta_seconds

    def render(self, surface: pygame.Surface) -> None:
        assert self._context is not None
        theme = self._context.theme.tokens
        gradient(surface, theme)
        self._buttons.clear()
        title = render_text("相机", 22, theme.text_primary, bold=True)
        surface.blit(title, (20, 20))
        preview_rect = self._preview_rect
        components.glass_card(surface, preview_rect, theme, alpha=250)
        inner = preview_rect.inflate(-8, -8)
        if self._preview_surface is not None:
            frame = pygame.transform.smoothscale(self._preview_surface, inner.size)
            surface.blit(frame, inner.topleft)
        else:
            pygame.draw.rect(surface, (13, 20, 29), inner, border_radius=18)
            hint = render_text(
                "相机预热中…" if not self._error else self._error,
                18,
                theme.text_secondary,
            )
            surface.blit(hint, hint.get_rect(center=inner.center))

        self._buttons["thumbnail"] = self._thumbnail_rect
        components.glass_card(surface, self._thumbnail_rect, theme, alpha=245)
        thumb_rect = self._thumbnail_rect.inflate(-6, -6)
        if self._latest_thumbnail is not None:
            surface.blit(
                pygame.transform.scale(self._latest_thumbnail, thumb_rect.size), thumb_rect
            )
            pygame.draw.rect(surface, theme.stroke, thumb_rect, 2, border_radius=10)
        else:
            components.icon(surface, "photo", self._thumbnail_rect.center, 25, theme.text_secondary)

        self._buttons["quality"] = self._quality_rect
        components.glass_card(surface, self._quality_rect, theme, alpha=245)
        surface.blit(
            render_text("像素", 14, theme.text_secondary),
            render_text("像素", 14, theme.text_secondary).get_rect(
                center=(self._quality_rect.centerx, self._quality_rect.y + 15)
            ),
        )
        quality_label = render_text(QUALITIES[self._quality], 18, theme.text_primary, bold=True)
        surface.blit(
            quality_label,
            quality_label.get_rect(center=(self._quality_rect.centerx, self._quality_rect.y + 37)),
        )

        self._buttons["shutter"] = self._shutter_rect
        pygame.draw.circle(surface, (250, 252, 255), self._shutter_rect.center, 34)
        pygame.draw.circle(surface, theme.accent, self._shutter_rect.center, 26)
        pygame.draw.circle(surface, (255, 255, 255), self._shutter_rect.center, 18)
        if self._busy:
            busy = render_text("拍摄中", 14, theme.accent, bold=True)
            surface.blit(busy, busy.get_rect(center=(self._shutter_rect.centerx, 452)))

        self._buttons["filter"] = self._filter_rect
        components.glass_card(surface, self._filter_rect, theme, alpha=245)
        filter_caption = render_text("风格", 14, theme.text_secondary)
        surface.blit(
            filter_caption,
            filter_caption.get_rect(center=(self._filter_rect.centerx, self._filter_rect.y + 15)),
        )
        filter_label = render_text(FILTERS[self._filter], 17, theme.text_primary, bold=True)
        surface.blit(
            filter_label,
            filter_label.get_rect(center=(self._filter_rect.centerx, self._filter_rect.y + 37)),
        )
        if self._filter_open:
            self._render_filter_picker(surface, theme)

    def _render_filter_picker(self, surface: pygame.Surface, theme: Any) -> None:
        panel = pygame.Rect(16, 262, 448, 100)
        components.glass_card(surface, panel, theme, alpha=252)
        caption = render_text("拍摄风格", 16, theme.text_primary, bold=True)
        surface.blit(caption, (28, 270))
        for index, rect in enumerate(self._style_rects):
            selected = index == self._filter
            pygame.draw.rect(
                surface,
                theme.accent if selected else theme.surface_elevated,
                rect,
                border_radius=10,
            )
            label = render_text(
                FILTERS[index],
                15,
                (255, 255, 255) if selected else theme.text_primary,
            )
            surface.blit(label, label.get_rect(center=rect.center))

    def set_manager(self, manager: Any) -> None:
        del manager

    async def leave(self, reason: LeaveReason) -> None:
        # Guide §7.1: leaving the page tears preview + worker down immediately.
        if self._preview_task is not None:
            self._preview_task.cancel()
            self._preview_task = None
        if self._camera is not None:
            await self._camera.shutdown(timeout=2.0)

    async def dispose(self) -> None:
        self._context = None
        self._camera = None
        self._preview_surface = None


def unused_subprocess_guard() -> subprocess.CompletedProcess[bytes] | None:  # pragma: no cover
    return None
