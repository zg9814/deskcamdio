"""Application mounting and lifecycle orchestration.

Rules (DEVELOPMENT_GUIDE §5.1):
- standby stays resident; the active business app is the only other resident;
- returning to the Launcher immediately leaves and disposes the app;
- leave() gets at most 500 ms before being abandoned to TaskScope cleanup;
- any fault inside lifecycle/input/update/render falls back to the Launcher,
  never out of the UI process.
"""

from __future__ import annotations

import asyncio
import logging
import time
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from deskcamdio.core.events import Event, EventBus
from deskcamdio.core.lifecycle import App, LeaveReason, RouteState
from deskcamdio.core.task_scope import TaskScope

LOGGER = logging.getLogger(__name__)

LEAVE_TIMEOUT = 0.5


@dataclass(frozen=True)
class AppDescriptor:
    app_id: str
    name: str
    icon: str
    order: int
    api_version: int
    entrypoint: str


def load_descriptors(apps_root: Path) -> list[AppDescriptor]:
    descriptors: list[AppDescriptor] = []
    for path in sorted(apps_root.glob("*/app.toml")):
        with path.open("rb") as handle:
            raw = tomllib.load(handle)
        if int(raw.get("api_version", 0)) != 2:
            LOGGER.warning("skip %s: api_version != 2", path.parent.name)
            continue
        descriptors.append(
            AppDescriptor(
                app_id=str(raw["id"]),
                name=str(raw["name"]),
                icon=str(raw.get("icon", "")),
                order=int(raw.get("order", 50)),
                api_version=2,
                entrypoint=str(raw["entrypoint"]),
            )
        )
    return sorted(descriptors, key=lambda d: d.order)


def instantiate(entrypoint: str) -> Any:
    module_name, _, class_name = entrypoint.partition(":")
    import importlib

    module = importlib.import_module(module_name)
    return getattr(module, class_name)()


@dataclass
class _Mounted:
    app_id: str
    app: App
    scope: TaskScope
    faulty: bool = False
    entered: bool = False


class _NullApp:
    """Minimal App stand-in for entries that fail during import."""

    async def mount(self, context: Any) -> None: ...

    async def enter(self, route: Any) -> None: ...

    def handle_input(self, event: Any) -> None: ...

    def update(self, delta_seconds: float) -> None: ...

    def render(self, surface: Any) -> None: ...

    async def leave(self, reason: Any) -> None: ...

    async def dispose(self) -> None: ...


class AppManager:
    def __init__(
        self,
        bus: EventBus,
        context_factory: Callable[[str, TaskScope], Any],
        apps_root: Path,
    ) -> None:
        self.bus = bus
        self._context_factory = context_factory
        self.descriptors = {d.app_id: d for d in load_descriptors(apps_root)}
        self.apps_root = apps_root
        self.disposed_log: list[tuple[str, dict[str, int]]] = []
        self._mounted: dict[str, _Mounted] = {}
        self.active_id: str = ""

    def descriptor_ids(self) -> list[str]:
        return list(self.descriptors)

    def is_mounted(self, app_id: str) -> bool:
        return app_id in self._mounted

    async def enter(self, route: RouteState, reason: LeaveReason = LeaveReason.SUPERSEDED) -> None:
        target = route.app_id
        if target not in self.descriptors:
            raise KeyError(f"unknown app {target}")
        if self.active_id and self.active_id != target:
            await self.leave_current(reason)
        if not self.is_mounted(target):
            await self._mount(target)
        mounted = self._mounted[target]
        if not mounted.faulty:
            try:
                await mounted.app.enter(route)
                mounted.entered = True
                self.active_id = target
                self.bus.publish("app.entered", app=target)
                return
            except Exception:  # noqa: BLE001 - faults fall back to launcher
                LOGGER.exception("enter failed for %s", target)
                mounted.faulty = True
        await self._fallback(target)

    async def _mount(self, app_id: str) -> None:
        descriptor = self.descriptors[app_id]
        started = time.monotonic()
        scope = TaskScope(name=f"app:{app_id}")
        try:
            app = instantiate(descriptor.entrypoint)
        except Exception:  # noqa: BLE001 - import errors are app faults too
            LOGGER.exception("load failed for %s", app_id)
            self._mounted[app_id] = _Mounted(
                app_id=app_id,
                app=_NullApp(),
                scope=scope,
                faulty=True,
            )
            asyncio.get_running_loop().create_task(self._fallback(app_id))
            return
        mounted = _Mounted(app_id=app_id, app=app, scope=scope)
        self._mounted[app_id] = mounted
        try:
            await app.mount(self._context_factory(app_id, scope))
            set_manager = getattr(app, "set_manager", None)
            if callable(set_manager):
                set_manager(self)
            LOGGER.info(
                "event=app_mounted app=%s duration_ms=%d",
                app_id,
                round((time.monotonic() - started) * 1000),
            )
        except Exception:  # noqa: BLE001
            LOGGER.exception("mount failed for %s", app_id)
            mounted.faulty = True

    async def leave_current(self, reason: LeaveReason = LeaveReason.NAVIGATED_BACK) -> None:
        if not self.active_id:
            return
        mounted = self._mounted.get(self.active_id)
        self.active_id = ""
        if mounted is None:
            return
        standby_kept = mounted.app_id == "standby"
        if not mounted.faulty and mounted.entered:
            try:
                await asyncio.wait_for(mounted.app.leave(reason), timeout=LEAVE_TIMEOUT)
            except TimeoutError:
                LOGGER.warning("leave timeout for %s; forcing cleanup", mounted.app_id)
            except Exception:  # noqa: BLE001
                LOGGER.exception("leave failed for %s", mounted.app_id)
            mounted.entered = False
        if standby_kept:
            return  # the aquarium home stays resident by design
        await self.dispose(mounted)

    async def dispose_all(self) -> None:
        for mounted in list(self._mounted.values()):
            await self.dispose(mounted)

    async def dispose(self, mounted: _Mounted) -> None:
        try:
            await mounted.app.dispose()
        except Exception:  # noqa: BLE001
            LOGGER.exception("dispose failed for %s", mounted.app_id)
        await mounted.scope.close()
        leftover = mounted.scope.leftover_counts()
        self.disposed_log.append((mounted.app_id, leftover))
        if any(leftover.values()):
            LOGGER.warning("event=app_leftover app=%s %s", mounted.app_id, leftover)
        else:
            LOGGER.info("event=app_disposed app=%s fd_delta=0", mounted.app_id)
        self._mounted.pop(mounted.app_id, None)

    async def _fallback(self, broken_app: str) -> None:
        mounted = self._mounted.pop(broken_app, None)
        if mounted is not None:
            await self.dispose(mounted)
        self.bus.publish("app.fault", app=broken_app)
        standby = "standby"
        if standby in self.descriptors:
            await self.enter(RouteState(app_id=standby), LeaveReason.FAULT)

    # ---- frame routing ---------------------------------------------------

    def handle_input(self, event: Any) -> bool:
        """Returns False when no healthy foreground app consumed it."""
        mounted = self._mounted.get(self.active_id)
        if mounted is None or mounted.faulty:
            return False
        try:
            mounted.app.handle_input(event)
            return True
        except Exception:  # noqa: BLE001
            LOGGER.exception("input fault for %s", mounted.app_id)
            mounted.faulty = True
            asyncio.get_running_loop().create_task(self._fallback(self.active_id))
            return False

    def update(self, delta_seconds: float) -> None:
        mounted = self._mounted.get(self.active_id)
        if mounted is None or mounted.faulty:
            return
        try:
            mounted.app.update(delta_seconds)
        except Exception:  # noqa: BLE001
            LOGGER.exception("update fault for %s", mounted.app_id)
            mounted.faulty = True
            asyncio.get_running_loop().create_task(self._fallback(self.active_id))

    def render(self, surface: Any) -> None:
        mounted = self._mounted.get(self.active_id)
        if mounted is None or mounted.faulty:
            return
        try:
            mounted.app.render(surface)
        except Exception:  # noqa: BLE001
            LOGGER.exception("render fault for %s", mounted.app_id)
            mounted.faulty = True
            asyncio.get_running_loop().create_task(self._fallback(self.active_id))


__all__ = [
    "AppDescriptor",
    "AppManager",
    "Event",
    "load_descriptors",
    "instantiate",
]
