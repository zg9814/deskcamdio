"""End-to-end test of the camera worker over a real Unix socket.

Runs only where AF_UNIX exists (skipped on Windows CI without it); the
worker subprocess is the real CLI entrypoint with a fake Picamera2 injected
via a stub module on sys.path, proving the full wire path.
"""

from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

unix_only = pytest.mark.skipif(
    not hasattr(socket, "AF_UNIX"), reason="requires AF_UNIX (Linux/macOS)"
)


@unix_only
async def test_subprocess_camera_roundtrip(tmp_path: Path) -> None:
    stub_root = tmp_path / "stubs"
    stub_root.mkdir()
    picam_stub = stub_root / "picamera2.py"
    picam_stub.write_text(
        textwrap.dedent(
            """
            class Picamera2:
                def create_video_configuration(self, main=None):
                    return {"main": main}

                def configure(self, config):
                    self.config = config

                def start(self):
                    pass

                def capture_array(self, name):
                    import array
                    w, h = 640, 360
                    return array.array("B", bytes(w * h * 3))

                def switch_mode_and_capture_file(self, config, path, format=None):
                    import array
                    size = config["main"]["size"]
                    data = bytes((size[0] * size[1] * 3) // 4)
                    from PIL import Image
                    image = Image.new("RGB", size)
                    image.save(path, "JPEG")

                def stop(self):
                    pass

                def close(self):
                    pass
            """
        ).strip(),
        encoding="utf-8",
    )

    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(stub_root), str(Path(__file__).resolve().parents[2] / "src")]
    )
    socket_path = tmp_path / "cam.sock"
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "deskcamdio.cli.camera_worker",
        "--socket",
        str(socket_path),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = asyncio.get_running_loop().time() + 5.0
        while not socket_path.exists():
            if asyncio.get_running_loop().time() > deadline:
                pytest.fail("worker socket never appeared")
            await asyncio.sleep(0.05)

        from deskcamdio.services.camera_client import SubprocessCameraClient

        client = SubprocessCameraClient(socket_path)
        client._process = process
        assert await client.ensure_running() is True
        frame = await client.preview_async()
        assert frame is not None and frame[:2] == b"\xff\xd8"

        destination = tmp_path / "shot.jpg"
        result = await client.capture("low", destination)
        assert destination.exists() and result["bytes"] > 0
        await client.shutdown(timeout=3.0)
        assert not socket_path.exists()
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
