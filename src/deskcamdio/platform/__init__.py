"""Platform selection helpers."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from deskcamdio.services.camera_client import BaseCameraClient


def current_platform() -> str:
    return os.environ.get("DESKCAMDIO_PLATFORM", "")


def create_camera_client(run_dir: Path) -> BaseCameraClient:
    if current_platform() == "raspberry_pi":
        from deskcamdio.services.camera_client import SubprocessCameraClient

        return SubprocessCameraClient(
            run_dir / "camera.sock",
            # -m keeps the spawn PATH-independent: systemd's default PATH has
            # no venv/bin, and console-script shebangs embed absolute paths.
            command=[
                sys.executable,
                "-m",
                "deskcamdio.cli.camera_worker",
                "--socket",
                str(run_dir / "camera.sock"),
            ],
        )
    from deskcamdio.platform.simulator import create_simulator_camera

    return create_simulator_camera()


def create_simulator_camera() -> BaseCameraClient:
    from deskcamdio.platform.simulator import create_simulator_camera as _factory

    return _factory(None)
