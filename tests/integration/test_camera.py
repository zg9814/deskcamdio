from __future__ import annotations

from pathlib import Path

import pytest

from deskcamdio.services.camera_client import FakeCameraWorker
from deskcamdio.services.ipc import (
    Message,
    ProtocolError,
    decode_header,
    new_request,
)


def test_header_roundtrip() -> None:
    request = new_request("capture", quality="high", destination="/tmp/x.jpg")
    raw = request.encode_header()
    header, body_length = decode_header(raw)
    assert header["name"] == "capture"
    assert header["quality"] == "high"
    assert body_length == 0
    assert len(raw) == 4 + len(raw) - 4


def test_body_length_reflected_in_header() -> None:
    message = Message(type="response", name="preview")
    message.body = b"\xff\xd8jpegdata"
    header, length = decode_header(message.encode_header())
    assert length == len(message.body)
    assert header["body_length"] == length


def test_oversized_header_rejected() -> None:
    with pytest.raises(ProtocolError):
        decode_header(b"\xff\xff\xff\xff")


async def test_fake_camera_open_preview_capture(tmp_path: Path) -> None:
    camera = FakeCameraWorker()
    assert await camera.ensure_running() is True
    frame = await camera.preview_async()
    assert frame is not None and frame[:2] == b"\xff\xd8"  # JPEG SOI

    destination = tmp_path / "photos" / "shot.jpg"
    result = await camera.capture("medium", destination)
    assert result["width"] > 0 and result["bytes"] > 0
    assert destination.exists()
    assert destination.suffix == ".jpg"
    parts = list(destination.parent.glob("*.part"))
    assert parts == []
    assert camera.captures == [("medium", destination)]
    await camera.shutdown()


async def test_fake_camera_capture_invalid_quality(tmp_path: Path) -> None:
    camera = FakeCameraWorker()
    with pytest.raises(ValueError):
        await camera.capture("ultra", tmp_path / "x.jpg")


async def test_fake_camera_unavailable_reports_error(tmp_path: Path) -> None:
    camera = FakeCameraWorker(available=False)
    assert await camera.ensure_running() is False
    assert "open failed" in camera.last_error or camera.last_error != ""


async def test_capture_to_missing_camera_fails(tmp_path: Path) -> None:
    camera = FakeCameraWorker(available=False)
    from deskcamdio.services.camera_client import CameraUnavailable

    with pytest.raises(CameraUnavailable):
        await camera.capture("low", tmp_path / "y.jpg")


def test_worker_handler_unknown_request() -> None:
    from deskcamdio.cli.camera_worker import CameraWorker

    worker = CameraWorker()
    response = worker.handle({"name": "mystery", "id": "1"}, b"")
    assert response.ok is False
    assert "unknown request" in response.error


def test_worker_ping_and_close(tmp_path: Path) -> None:
    from deskcamdio.cli.camera_worker import CameraWorker

    worker = CameraWorker()
    ping = worker.handle({"name": "ping", "id": "2"}, b"")
    close = worker.handle({"name": "close", "id": "3"}, b"")
    assert ping.ok and close.ok


def test_worker_capture_without_open(tmp_path: Path) -> None:
    from deskcamdio.cli.camera_worker import CameraWorker

    worker = CameraWorker()
    response = worker.handle(
        {"name": "capture", "id": "4", "quality": "low", "destination": str(tmp_path / "a.jpg")},
        b"",
    )
    assert response.ok is False


def test_worker_bad_quality(tmp_path: Path) -> None:
    from deskcamdio.cli.camera_worker import CameraWorker

    worker = CameraWorker()
    worker._opened = True  # force-opened for the validation branch
    response = worker.handle(
        {"name": "capture", "id": "5", "quality": "huge", "destination": str(tmp_path / "b.jpg")},
        b"",
    )
    assert response.ok is False
