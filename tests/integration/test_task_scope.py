from __future__ import annotations

import asyncio
import subprocess
import sys
import time
from typing import Any

import pytest

from deskcamdio.core.task_scope import TaskScope


async def test_create_task_and_cancel_on_close() -> None:
    scope = TaskScope("t")
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def worker() -> None:
        started.set()
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    scope.create_task(worker(), name="worker")
    await started.wait()
    assert not scope.closed
    await scope.close()
    assert cancelled.is_set()
    assert scope.leftover_counts()["tasks"] == 0


async def test_closed_scope_refuses_work() -> None:
    async def noop_coro() -> None: ...

    scope = TaskScope("t")
    await scope.close()
    with pytest.raises(RuntimeError):
        scope.create_task(noop_coro())
    with pytest.raises(RuntimeError):
        scope.run_in_thread(lambda: None)
    with pytest.raises(RuntimeError):
        scope.track_subscription(lambda: None)


async def test_unsubscribe_called_once_per_registration() -> None:
    calls: list[str] = []
    scope = TaskScope("t")
    scope.track_subscription(lambda: calls.append("a"), name="a")
    scope.track_subscription(lambda: calls.append("b"), name="b")
    scope.track_subscription(lambda: (_ for _ in ()).throw(ValueError()), name="bad")
    await scope.close()
    assert calls == ["a", "b"]


async def test_process_reaped_via_terminate() -> None:
    scope = TaskScope("proc")
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    scope.track_process(proc, name="sleeper")
    deadline = time.monotonic() + 2.0
    while proc.poll() is None and time.monotonic() < deadline:
        await asyncio.sleep(0.01)
    await scope.close()
    assert proc.poll() is not None


async def test_thread_joined_and_leftovers_reported() -> None:
    done = threading_event()
    scope = TaskScope("thr")
    scope.run_in_thread(lambda: (time.sleep(0.05), done.set()), name="quick")
    await scope.close()
    assert done.is_set()
    assert scope.leftover_counts()["threads"] == 0
    assert scope.leftover_counts()["processes"] == 0


def threading_event() -> Any:
    import threading

    return threading.Event()
