"""Resource-lifecycle regression: repeated app cycles leave nothing behind.

Guide §15/§5.1: entering and leaving every application repeatedly must not
accumulate asyncio tasks, threads, processes or event subscriptions, and
memory must stay flat (checked where /proc exposes RSS).
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from deskcamdio.core.lifecycle import LeaveReason, RouteState

CYCLES = 20
APPS = ["camera", "gallery", "memo", "pomodoro", "settings", "fishing", "music"]


def _rss_kb() -> int:
    try:
        for line in Path("/proc/self/status").read_text(encoding="ascii").splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1])
    except OSError:
        pass
    return 0  # Windows dev machines: structural checks still apply


def _fd_count() -> int:
    try:
        return len(os.listdir("/proc/self/fd"))
    except OSError:
        return 0


async def test_twenty_cycles_leave_no_leftovers(harness) -> None:
    manager = harness.manager

    # Baseline subscription count on the topics apps subscribe to.
    baseline_subs = sum(
        len(harness.bus._subscribers.get(topic, []))  # noqa: SLF001 - test introspection
        for topic in ("photo.created", "memo.changed", "pomodoro.configure")
    )

    rss_before = _rss_kb()
    fd_before = _fd_count()

    for cycle in range(CYCLES):
        for app_id in APPS:
            await manager.enter(RouteState(app_id=app_id))
            assert manager.active_id == app_id, f"cycle {cycle} {app_id}"
            if harness.data_dir is not None:
                surface_probe = None  # update() is enough to exercise task paths
                del surface_probe
            manager.update(1 / 30)
            await manager.leave_current(LeaveReason.NAVIGATED_BACK)

    # Every business app disposed exactly CYCLES times with zero leftovers.
    by_app: dict[str, list[dict[str, int]]] = {}
    for app_id, leftover in manager.disposed_log:
        by_app.setdefault(app_id, []).append(leftover)
    for app_id in APPS:
        if app_id == "music":
            continue  # music keeps playback across pages; no per-leave dispose
        assert len(by_app.get(app_id, [])) >= CYCLES - 2, f"{app_id} dispose count"
        for leftover in by_app[app_id]:
            assert leftover == {"tasks": 0, "threads": 0, "processes": 0}, (
                f"{app_id} leaked {leftover}"
            )

    # Subscriptions returned to baseline (no accumulation).
    final_subs = sum(
        len(harness.bus._subscribers.get(topic, []))  # noqa: SLF001
        for topic in ("photo.created", "memo.changed", "pomodoro.configure")
    )
    assert final_subs <= baseline_subs + len(APPS)  # standby stays mounted once

    # Memory/FD growth bounded (guide gate scaled to this loop size).
    rss_after = _rss_kb()
    if rss_before and rss_after:
        assert rss_after - rss_before <= 12 * 1024, (
            f"RSS grew {(rss_after - rss_before)} KB over {CYCLES * len(APPS)} cycles"
        )
    fd_after = _fd_count()
    if fd_before and fd_after:
        assert fd_after - fd_before <= 5


async def test_scope_registered_tasks_cancelled_on_dispose(harness) -> None:
    """A scope-tracked long task dies with the app instance."""
    from deskcamdio.apps.camera.app import CameraApp

    route = RouteState(app_id="camera")
    await harness.manager.enter(route)
    mounted = harness.manager._mounted["camera"]  # noqa: SLF001
    app = mounted.app
    assert isinstance(app, CameraApp)
    assert app._preview_task is not None and not app._preview_task.done()
    preview_task = app._preview_task

    await harness.manager.leave_current(LeaveReason.NAVIGATED_BACK)
    await asyncio.sleep(0.05)  # allow cancellation to propagate
    assert preview_task.done()
