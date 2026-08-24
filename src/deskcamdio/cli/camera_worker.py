"""Camera worker process: owns Picamera2 so the UI main process never does.

Wire format lives in :mod:`deskcamdio.services.ipc`. Requests: ping, open,
preview, capture, close. The worker exits after close or peer disconnect.
"""

from __future__ import annotations

import argparse
import io
import logging
import os
import socket
import sys
import time
from pathlib import Path
from typing import Any

from deskcamdio.services.ipc import (
    Message,
    ProtocolError,
    recv_message,
    send_message,
)

LOGGER = logging.getLogger("camera-worker")

PREVIEW_SIZE = (640, 360)
JPEG_QUALITY = 72
MAX_PREVIEW_BYTES = 256 * 1024
CAPTURE_SIZES = {
    "low": (1536, 864),
    "medium": (2304, 1296),
    "high": (4608, 2592),
}


class CameraWorker:
    """Camera state + pure request handling (unit-testable without hardware)."""

    def __init__(self) -> None:
        self._picam: Any = None
        self._last_preview: bytes = b""
        self._opened = False
        self._still_configs: dict[str, Any] = {}

    # ---- camera plumbing (Pi only) ---------------------------------------

    def open_camera(self) -> None:
        if self._opened:
            return
        from picamera2 import Picamera2  # heavy native import stays in this process

        self._picam = Picamera2()
        config = self._picam.create_video_configuration(
            main={"size": PREVIEW_SIZE, "format": "RGB888"}
        )
        self._picam.configure(config)
        self._still_configs = {
            quality: self._picam.create_still_configuration(
                main={"size": size, "format": "RGB888"},
                buffer_count=1,
            )
            for quality, size in CAPTURE_SIZES.items()
        }
        self._picam.start()
        self._opened = True

    def close_camera(self) -> None:
        if not self._opened:
            return
        try:
            self._picam.stop()
            self._picam.close()
        except Exception:  # noqa: BLE001 - best-effort teardown
            LOGGER.exception("picamera teardown failed")
        finally:
            self._opened = False

    def _encode_preview(self) -> bytes:
        try:
            frame = self._picam.capture_array("main")
        except Exception:  # noqa: BLE001 - transient sensor errors keep last frame
            return b""
        return encode_rgb_as_jpeg(frame, PREVIEW_SIZE[0], PREVIEW_SIZE[1])

    def capture_to(self, destination: Path, quality: str) -> tuple[int, int, int]:
        size = CAPTURE_SIZES.get(quality)
        if size is None:
            raise ValueError(f"invalid quality {quality}")
        if not self._opened:
            raise RuntimeError("camera not open")
        destination.parent.mkdir(parents=True, exist_ok=True)
        part = destination.with_suffix(".jpg.part")
        config = self._still_configs.get(quality)
        if config is None:
            raise RuntimeError(f"still configuration unavailable for {quality}")
        self._picam.switch_mode_and_capture_file(config, str(part), format="jpeg")
        data = part.read_bytes()
        if not data:
            raise RuntimeError("empty capture")
        with part.open("rb+") as handle:
            os.fsync(handle.fileno())
        width, height = jpeg_dimensions(data)
        part.replace(destination)
        return width, height, len(data)

    # ---- request dispatch --------------------------------------------------

    def handle(self, header: dict[str, Any], body: bytes) -> Message:
        name = str(header.get("name"))
        request = Message(type="request", name=name, id=str(header.get("id", "")))
        if name == "ping":
            from deskcamdio.services.ipc import response_for

            return response_for(request)
        if name == "open":
            from deskcamdio.services.ipc import response_for

            try:
                self.open_camera()
                return response_for(request)
            except Exception as exc:  # noqa: BLE001
                LOGGER.exception("open failed")
                return response_for(request, ok=False, error=str(exc), error_code="CAMERA_OPEN")
        if name == "preview":
            from deskcamdio.services.ipc import response_for

            jpeg = self._encode_preview() if self._opened else b""
            if jpeg:
                self._last_preview = jpeg
            else:
                jpeg = self._last_preview
            if len(jpeg) > MAX_PREVIEW_BYTES:
                jpeg = b""
            response = response_for(request, size=len(jpeg))
            response.body = jpeg
            return response
        if name == "capture":
            from deskcamdio.services.ipc import response_for

            started = time.monotonic()
            destination = Path(str(header.get("destination", "")))
            quality = str(header.get("quality", "medium"))
            try:
                width, height, size_bytes = self.capture_to(destination, quality)
            except Exception as exc:  # noqa: BLE001
                LOGGER.exception("capture failed")
                destination.with_suffix(".jpg.part").unlink(missing_ok=True)
                code = "INVALID_QUALITY" if isinstance(exc, ValueError) else "CAPTURE_FAILED"
                return response_for(request, ok=False, error=str(exc), error_code=code)
            return response_for(
                request,
                width=width,
                height=height,
                bytes=size_bytes,
                duration_ms=round((time.monotonic() - started) * 1000),
            )
        if name == "close":
            from deskcamdio.services.ipc import response_for

            return response_for(request)
        from deskcamdio.services.ipc import response_for

        return response_for(request, ok=False, error=f"unknown request {name}")


def encode_rgb_as_jpeg(frame: Any, width: int, height: int) -> bytes:
    """Encode an RGB888 buffer; simplejpeg preferred, Pillow fallback."""
    try:
        import simplejpeg

        return simplejpeg.encode_jpeg(frame, quality=JPEG_QUALITY, colorspace="RGB")
    except ImportError:
        pass
    from PIL import Image

    image = Image.frombuffer("RGB", (width, height), bytes(frame), "raw", "RGB", 0, 1)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=JPEG_QUALITY)
    return buffer.getvalue()


def jpeg_dimensions(data: bytes) -> tuple[int, int]:
    try:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as image:
            return image.width, image.height
    except Exception:  # noqa: BLE001 - dimensions are informational only
        return (0, 0)


def _make_unix_server(socket_path: Path) -> socket.socket | None:
    family = getattr(socket, "AF_UNIX", None)
    if family is None:
        return None
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    socket_path.unlink(missing_ok=True)
    pid_path = socket_path.with_suffix(".pid")
    pid_path.write_text(str(os.getpid()), encoding="ascii")
    server = socket.socket(family, socket.SOCK_STREAM)
    server.bind(str(socket_path))
    server.listen(1)
    server.settimeout(10.0)
    return server


def _serve_client(conn: socket.socket, worker: CameraWorker) -> None:
    """Handle requests until close or disconnect."""
    while True:
        message = recv_message(conn)
        if message.type != "request":
            continue
        header = {
            "type": message.type,
            "name": message.name,
            "id": message.id,
            **message.payload,
            "body_length": len(message.body),
        }
        response = worker.handle(header, message.body)
        send_message(conn, response)
        if message.name == "close":
            break


def serve(
    socket_path: Path,
    worker: CameraWorker | None = None,
    *,
    server: socket.socket | None = None,
) -> int:
    """Serve one client until close or disconnect; cleans up socket/pid."""
    worker = worker or CameraWorker()
    owned_server = server is None
    if owned_server:
        maybe_server = _make_unix_server(socket_path)
        if maybe_server is None:
            raise RuntimeError("Unix sockets unavailable on this host")
        server = maybe_server
    assert server is not None
    exit_code = 0
    try:
        LOGGER.info("event=camera_worker_started socket=%s", socket_path)
        conn, _peer = server.accept()
        conn.settimeout(30.0)
        with conn:
            _serve_client(conn, worker)
    except (TimeoutError, ConnectionError):
        LOGGER.info("event=camera_worker_stopped reason=peer_lost")
    except ProtocolError as exc:
        LOGGER.error("event=camera_worker_stopped reason=%s", exc)
    except Exception:  # noqa: BLE001
        LOGGER.exception("camera worker crashed")
        exit_code = 1
    finally:
        worker.close_camera()
        server.close()
        if owned_server:
            socket_path.unlink(missing_ok=True)
            socket_path.with_suffix(".pid").unlink(missing_ok=True)
        LOGGER.info("event=camera_worker_stopped reason=clean fd_delta=0")
    return exit_code


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    parser = argparse.ArgumentParser(prog="deskcamdio-camera-worker")
    parser.add_argument("--socket", required=True, type=Path)
    args = parser.parse_args(argv)
    return serve(args.socket)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
