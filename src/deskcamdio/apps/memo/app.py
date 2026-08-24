"""Memo: add, complete, delete via StateStore; change events keep UI fresh."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pygame

from deskcamdio.core.lifecycle import App, LeaveReason, RouteState
from deskcamdio.core.runtime import RuntimeContext
from deskcamdio.ui import components
from deskcamdio.ui.aquarium import ambient, seabed
from deskcamdio.ui.typography import draw_wrapped, render_text


class MemoApp(App):
    def __init__(self) -> None:
        self._context: RuntimeContext | None = None
        self._unsub_changed: Callable[[], None] | None = None
        self.memos: list[dict] = []
        self._rows: dict[str, pygame.Rect] = {}
        self._input_box = pygame.Rect(16, 52, 360, 44)
        self._draft = "记事…"

    def _spawn(self, coro: Any, *, name: str | None = None) -> Any:
        """Schedule work on this app's TaskScope; returns the Task."""
        import asyncio

        ctx = self._context
        scope = getattr(ctx, "scope", None) if ctx is not None else None
        if scope is not None:
            return scope.create_task(coro, name=name)
        return asyncio.get_running_loop().create_task(coro, name=name)

    async def mount(self, context: RuntimeContext) -> None:
        self._context = context

        def on_changed(_event: Any) -> None:
            import asyncio

            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                return  # published from a non-async context; UI reloads on enter
            loop.create_task(self._reload())

        self._unsub_changed = context.bus.subscribe("memo.changed", on_changed)
        if getattr(context, "scope", None) is not None:
            context.scope.track_subscription(self._unsub_changed, name="memo:changed")  # noqa: E501
        await self._reload()

    async def _reload(self) -> None:
        context = self._context
        if context is not None:
            self.memos = await context.store.list_memos()

    async def enter(self, route: RouteState) -> None:
        await self._reload()

    def handle_input(self, event: pygame.event.Event) -> None:
        context = self._context
        if context is None or event.type != pygame.MOUSEBUTTONDOWN:
            return
        for key, rect in self._rows.items():
            if not rect.collidepoint(event.pos):
                continue
            kind, _, arg = key.partition(":")
            if kind == "toggle":
                self._spawn(
                    context.store.set_memo_completed(int(arg), not self._completed(int(arg)))
                )
            elif kind == "delete":
                self._spawn(context.store.delete_memo(int(arg)))
            break

    def _completed(self, memo_id: int) -> bool:
        return any(m["id"] == memo_id and m["completed"] for m in self.memos)

    def update(self, delta_seconds: float) -> None:
        del delta_seconds

    def render(self, surface: pygame.Surface) -> None:
        assert self._context is not None
        theme = self._context.theme.tokens
        elapsed = pygame.time.get_ticks() / 1000.0
        ambient(surface, theme, elapsed * 0.3)
        header = render_text(f"备忘 · {len(self.memos)} 条", 20, theme.text_primary, bold=True)
        surface.blit(header, (16, 12))

        self._rows.clear()
        visible = self.memos[:4]
        row_rect = pygame.Rect(16, 56, 448, 86)
        for index, memo in enumerate(visible):
            rect = row_rect.copy()
            rect.y += index * 92
            mark = "●" if memo["completed"] else "○"
            components.card(surface, rect, theme, elevated=bool(memo["completed"]), radius=14)
            mark_surface = render_text(mark, 18, theme.accent, bold=True)
            surface.blit(mark_surface, mark_surface.get_rect(midleft=(rect.x + 14, rect.centery)))
            draw_wrapped(
                surface,
                str(memo["body"]),
                pygame.Rect(rect.x + 42, rect.y + 8, 328, rect.height - 16),
                17,
                theme.text_primary,
                line_gap=2,
            )
            delete = render_text("删", 15, theme.text_secondary)
            surface.blit(delete, delete.get_rect(center=(rect.right - 31, rect.centery)))
            self._rows[f"toggle:{memo['id']}"] = pygame.Rect(rect.x, rect.y, 380, rect.height)
            self._rows[f"delete:{memo['id']}"] = pygame.Rect(
                rect.right - 62, rect.y, 62, rect.height
            )
        if not visible:
            seabed(surface, theme, elapsed * 0.2)
            card = pygame.Rect(48, 94, 384, 210)
            components.glass_card(surface, card, theme, alpha=216)
            components.icon(surface, "notes", (240, 146), 38, theme.accent)
            hint = render_text("今天还没有备忘", 20, theme.text_primary, bold=True)
            surface.blit(hint, hint.get_rect(center=(240, 200)))
            sub = render_text("短按旋钮，说“记一下…”即可添加", 15, theme.text_secondary)
            surface.blit(sub, sub.get_rect(center=(240, 238)))

    async def leave(self, reason: LeaveReason) -> None:
        del reason

    async def dispose(self) -> None:
        if self._unsub_changed is not None:
            self._unsub_changed()
            self._unsub_changed = None
        self._context = None
        self.memos.clear()
        self._rows.clear()
