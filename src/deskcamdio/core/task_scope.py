"""Ownership-scoped resource registry.

Every async task, thread, subscription and child process created inside one
logical lifetime registers here so ``close()`` can unwind them in a fixed,
bounded order (DEVELOPMENT_GUIDE §5.2).
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import threading
from collections.abc import Callable, Coroutine
from typing import Any

LOGGER = logging.getLogger(__name__)

_JOIN_TIMEOUT = 0.5


class TaskScope:
    """Owns every background resource created within one lifetime."""

    def __init__(self, name: str = "scope") -> None:
        self.name = name
        self._closed = False
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._subscriptions: list[tuple[str, Callable[[], Any]]] = []
        self._processes: dict[str, subprocess.Popen[Any]] = {}

    @property
    def closed(self) -> bool:
        return self._closed

    def create_task(
        self, coroutine: Coroutine[Any, Any, None], name: str | None = None
    ) -> asyncio.Task[None]:
        if self._closed:
            coroutine.close()
            raise RuntimeError(f"scope {self.name} is closed")
        task_name = f"{self.name}:{name or getattr(coroutine, '__name__', 'task')}"
        task = asyncio.get_running_loop().create_task(coroutine, name=task_name)
        self._tasks[task_name] = task
        task.add_done_callback(lambda done: self._tasks.pop(done.get_name(), None))
        return task

    def run_in_thread(
        self, function: Callable[..., Any], name: str | None = None
    ) -> threading.Thread:
        if self._closed:
            raise RuntimeError(f"scope {self.name} is closed")
        thread_name = f"{self.name}:{name or getattr(function, '__name__', 'thread')}"
        thread = threading.Thread(target=function, name=thread_name, daemon=True)
        self._threads[thread_name] = thread
        thread.start()
        return thread

    def track_subscription(
        self, unsubscribe: Callable[[], Any], name: str = "subscription"
    ) -> None:
        if self._closed:
            raise RuntimeError(f"scope {self.name} is closed")
        self._subscriptions.append((name, unsubscribe))

    def track_process(self, process: subprocess.Popen[Any], name: str = "process") -> None:
        if self._closed:
            raise RuntimeError(f"scope {self.name} is closed")
        self._processes[f"{self.name}:{name}"] = process

    def leftover_counts(self) -> dict[str, int]:
        return {
            "tasks": len(self._tasks),
            "threads": sum(t.is_alive() for t in self._threads.values()),
            "processes": sum(p.poll() is None for p in self._processes.values()),
        }

    async def close(self) -> None:
        """Unwind resources: cancel tasks, unsubscribe, reap processes."""
        if self._closed:
            return
        self._closed = True

        for task in list(self._tasks.values()):
            task.cancel()
        await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        self._tasks.clear()

        for name, unsubscribe in self._subscriptions:
            try:
                unsubscribe()
            except Exception:  # noqa: BLE001 - cleanup must continue
                LOGGER.exception("unsubscribe failed for %s", name)
        self._subscriptions.clear()

        for name, process in self._processes.items():
            self._reap(name, process)
        self._processes.clear()

        for name, thread in self._threads.items():
            if thread.is_alive():
                thread.join(timeout=_JOIN_TIMEOUT)
                if thread.is_alive():
                    LOGGER.warning("thread=%s did not exit within %.2fs", name, _JOIN_TIMEOUT)
        self._threads.clear()

    @staticmethod
    def _reap(name: str, process: subprocess.Popen[Any]) -> None:
        if process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=_JOIN_TIMEOUT)
            return
        except subprocess.TimeoutExpired:
            LOGGER.warning("process=%s ignored terminate; killing", name)
        process.kill()
        try:
            process.wait(timeout=_JOIN_TIMEOUT)
        except subprocess.TimeoutExpired:  # pragma: no cover - kill rarely fails
            LOGGER.error("process=%s survived kill", name)


def noop() -> None:
    """Trivial unsubscribe used by tests and placeholder wiring."""
