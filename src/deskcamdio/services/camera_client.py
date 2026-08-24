"""Camera client for the UI process.

Two transports behind one interface:
- :class:`SubprocessCameraClient` spawns ``deskcamdio.cli.camera_worker``
  (Pi) and talks over a Unix socket;
- :class:`FakeCameraWorker` runs the same handler object in-process with a
  synthetic JPEG source, so Windows simulator and tests exercise identical
  request/response logic without sockets.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import socket
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from deskcamdio.services.ipc import Message

LOGGER = logging.getLogger(__name__)

PREVIEW_W, PREVIEW_H = 640, 360


class CameraUnavailable(RuntimeError):
    pass


def _to_thread(func: Callable[..., Any], /, *args: Any) -> Any:
    return asyncio.get_running_loop().run_in_executor(None, func, *args)


class BaseCameraClient:
    """Shared request plumbing; subclasses provide running/_exchange."""

    def __init__(self) -> None:
        self._open_tried = False
        self._last_error = ""

    @property
    def running(self) -> bool:
        raise NotImplementedError

    async def ensure_running(self) -> bool:
        if self._open_tried:
            return self.running and not self._last_error
        self._open_tried = True
        response = await self._request("open")
        if not response.ok:
            self._last_error = response.error or "camera open failed"
            return False
        return True

    @property
    def last_error(self) -> str:
        return self._last_error

    def preview_jpeg(self) -> bytes | None:
        return None

    async def preview_async(self) -> bytes | None:
        response = await self._request("preview")
        if response.ok and response.body:
            return response.body
        return None

    async def capture(self, quality: str, destination: Path) -> dict[str, Any]:
        if quality not in {"low", "medium", "high"}:
            raise ValueError(f"invalid quality {quality}")
        response = await self._request("capture", quality=quality, destination=str(destination))
        if not response.ok:
            raise CameraUnavailable(response.error or "capture failed")
        return dict(response.payload)

    async def shutdown(self, timeout: float = 2.0) -> None:  # noqa: ARG002
        with contextlib.suppress(Exception):
            await asyncio.wait_for(self._request("close"), timeout=timeout)

    async def _request(self, name: str, **payload: Any) -> Message:
        header: dict[str, Any] = {"type": "request", "name": name, "body_length": 0, **payload}
        return await self._exchange(header)

    async def _exchange(self, header: dict[str, Any]) -> Message:
        raise NotImplementedError


class SubprocessCameraClient(BaseCameraClient):
    def __init__(self, socket_path: Path, command: list[str] | None = None) -> None:
        super().__init__()
        self.socket_path = socket_path
        # -m form is PATH-independent (systemd PATH lacks venv/bin) and immune
        # to console-script shebangs embedding absolute build paths.
        self.command = command or [
            sys.executable,
            "-m",
            "deskcamdio.cli.camera_worker",
            "--socket",
            str(socket_path),
        ]
        self._process: Any = None
        self._sock: socket.socket | None = None
        self._lock = asyncio.Lock()

    @property
    def running(self) -> bool:
        if self._sock is None:
            return False
        if self._process is None:
            return True
        return self._process.returncode is None

    async def start(self) -> bool:
        if self.running:
            return True
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        self._process = await asyncio.create_subprocess_exec(*self.command)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + 2.5
        while loop.time() < deadline:
            if self.socket_path.exists():
                break
            await asyncio.sleep(0.05)
        else:
            await self.shutdown(0.1)
            raise CameraUnavailable("camera worker did not become ready in 2.5s")
        family = getattr(socket, "AF_UNIX", None)
        if family is None:
            raise CameraUnavailable("Unix sockets unavailable on this host")
        sock = socket.socket(family, socket.SOCK_STREAM)
        await _to_thread(sock.connect, str(self.socket_path))
        sock.settimeout(30.0)
        self._sock = sock
        return True

    async def _exchange(self, header: dict[str, Any]) -> Message:
        from deskcamdio.services.ipc import recv_message, send_message

        if not self.running:
            await self.start()
        assert self._sock is not None
        message = Message(
            type="request",
            name=str(header["name"]),
            payload={k: v for k, v in header.items() if k != "name"},
        )
        async with self._lock:
            await _to_thread(send_message, self._sock, message)
            return await _to_thread(recv_message, self._sock)

    async def shutdown(self, timeout: float = 2.0) -> None:
        await super().shutdown(timeout)
        if self._sock is not None:
            self._sock.close()
            self._sock = None
        if self._process is not None and self._process.returncode is None:
            try:
                await asyncio.wait_for(self._process.wait(), timeout=min(timeout, 1.0))
            except TimeoutError:
                self._process.terminate()
                try:
                    await asyncio.wait_for(self._process.wait(), timeout=1.0)
                except TimeoutError:
                    self._process.kill()
                    await self._process.wait()
            except ProcessLookupError:
                pass
        self._process = None
        self.socket_path.unlink(missing_ok=True)
        self.socket_path.with_suffix(".pid").unlink(missing_ok=True)


class FakeCameraWorker(BaseCameraClient):
    """In-process camera used by the simulator; identical handler logic."""

    def __init__(self, available: bool = True) -> None:
        super().__init__()
        self.available = available
        self.frame_counter = 0
        self.captures: list[tuple[str, Path]] = []

    @property
    def running(self) -> bool:
        return self.available

    def _synthetic_jpeg(self, width: int = 320, height: int = 180) -> bytes:
        from deskcamdio.cli.camera_worker import encode_rgb_as_jpeg

        row = bytearray()
        shade = (self.frame_counter * 7) % 255
        for x in range(width):
            r = (x * 255 // width + shade) % 256
            row += bytes((r, (shade + 60) % 256, 90))
        frame = bytes(row) * height
        self.frame_counter += 1
        return encode_rgb_as_jpeg(frame, width, height)

    async def _exchange(self, header: dict[str, Any]) -> Message:
        from deskcamdio.cli.camera_worker import CameraWorker

        if not hasattr(self, "_worker"):
            self._worker = CameraWorker()

        class FakePicam:
            def create_still_configuration(_self, **kwargs: Any) -> dict[str, Any]:
                return dict(kwargs)

            def capture_array(_self, _name: str) -> bytes:
                return bytes(PREVIEW_W * PREVIEW_H * 3)

            def switch_mode_and_capture_file(
                _self, _config: dict, path: Path, format: str | None = None
            ) -> None:
                quality_size = {
                    "low": (1536, 864),
                    "medium": (2304, 1296),
                    "high": (4608, 2592),
                }
                width, height = quality_size[str(header.get("quality", "medium"))]
                Path(path).write_bytes(self._synthetic_jpeg(width // 12, height // 12))

            def stop(_self) -> None: ...

            def close(_self) -> None: ...

        if not hasattr(self, "_patched"):
            self._worker._picam = FakePicam()
            self._worker._opened = self.available
            self._worker._still_configs = {
                name: {"main": {"size": size, "format": "RGB888"}}
                for name, size in {
                    "low": (1536, 864),
                    "medium": (2304, 1296),
                    "high": (4608, 2592),
                }.items()
            }
            self._patched = True

        body = b""
        if str(header["name"]) == "preview":
            body = self._synthetic_jpeg() if self.available else b""
        worker_header = {**header, "body_length": len(body)}
        response = self._worker.handle(worker_header, body)
        if str(header["name"]) == "capture":
            self.captures.append((str(header.get("quality")), Path(str(header.get("destination")))))
        return response

    async def shutdown(self, timeout: float = 2.0) -> None:
        self.available = False
