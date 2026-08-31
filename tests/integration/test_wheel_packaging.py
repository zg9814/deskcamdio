"""Wheel packaging gate: manifests and assets must ship (marked 'wheel')."""

from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.wheel

ROOT = Path(__file__).resolve().parents[2]


def build_wheel(outdir: Path) -> Path:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "build",
            "--wheel",
            "--no-isolation",
            "--outdir",
            str(outdir),
            str(ROOT),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=600,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    wheels = list(outdir.glob("deskcamdio-*.whl"))
    assert wheels, "no wheel produced"
    return wheels[0]


@pytest.fixture(scope="module")
def wheel_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return build_wheel(tmp_path_factory.mktemp("wheelbuild"))


def test_wheel_ships_all_app_manifests(wheel_path: Path) -> None:
    names = _names(wheel_path)
    app_tomls = [n for n in names if n.startswith("deskcamdio/apps/") and n.endswith("/app.toml")]
    assert len(app_tomls) >= 10, f"expected >=10 manifests, got {app_tomls}"


def test_wheel_ships_cjk_font_and_license(wheel_path: Path) -> None:
    names = _names(wheel_path)
    assert any(n.startswith("deskcamdio/assets/fonts/NotoSansSC") for n in names)
    assert any(n.endswith("assets/fonts/OFL.txt") for n in names)


def test_wheel_ships_sound_assets(wheel_path: Path) -> None:
    names = _names(wheel_path)
    wavs = [n for n in names if n.startswith("deskcamdio/assets/sounds/") and n.endswith(".wav")]
    assert {"tap", "shutter", "alarm", "error"} <= {Path(n).stem for n in wavs}


def test_wheel_ships_generated_ui_art(wheel_path: Path) -> None:
    names = _names(wheel_path)
    art_pngs = [
        name
        for name in names
        if name.startswith("deskcamdio/assets/art/") and name.endswith(".png")
    ]
    assert len(art_pngs) == 76
    assert any(name.endswith("aquarium-far-aquatic-480-v1.png") for name in art_pngs)
    assert any(name.endswith("state-camera-unavailable-160x112-v1.png") for name in art_pngs)


def _names(wheel: Path) -> list[str]:
    with zipfile.ZipFile(wheel) as bundle:
        return bundle.namelist()
