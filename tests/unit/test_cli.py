from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

import deskcamdio.cli.device as device
import deskcamdio.cli.selftest as selftest
from deskcamdio import __version__


def test_version_is_single_sourced() -> None:
    from deskcamdio._version import __version__ as raw

    assert raw == __version__ == "1.0.0rc2.post1"


def test_device_boots_one_frame(tmp_path: Path) -> None:
    exit_code = device.main(
        [
            "--headless",
            "--frames",
            "1",
            "--data-dir",
            str(tmp_path / "data"),
            "--run-dir",
            str(tmp_path / "run"),
        ]
    )
    assert exit_code == 0


def test_device_unknown_flag_fails(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        device.main(["--unknown-flag"])
    assert excinfo.value.code == 2


def test_selftest_ok_under_dummy_driver(capsys: pytest.CaptureFixture[str]) -> None:
    assert selftest.main() == 0
    assert "selftest OK" in capsys.readouterr().out


def test_console_script_module_runs(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "deskcamdio.cli.device",
            "--headless",
            "--frames",
            "1",
            "--data-dir",
            str(tmp_path / "data"),
            "--run-dir",
            str(tmp_path / "run"),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert result.returncode == 0
