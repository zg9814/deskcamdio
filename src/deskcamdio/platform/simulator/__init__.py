"""Simulator platform fakes (Windows dev / CI)."""

from __future__ import annotations

from pathlib import Path

from deskcamdio.services.camera_client import FakeCameraWorker


def create_simulator_camera(_socket_dir: Path | None = None) -> FakeCameraWorker:
    return FakeCameraWorker()
