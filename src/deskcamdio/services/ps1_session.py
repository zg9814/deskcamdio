"""RetroArch + PCSX-ReARMed process lifecycle for PS1 games."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import IO, Any

from deskcamdio.services.game_session import GameSession

DEFAULT_RETROARCH = Path("/var/lib/deskcamdio/tools/retroarch/usr/bin/retroarch")
DEFAULT_PCSX_CORE = Path("/var/lib/deskcamdio/tools/libretro/pcsx_rearmed_libretro.so")


class RetroArchSession(GameSession):
    def __init__(
        self,
        retroarch_binary: Path,
        core_path: Path,
        content_path: Path,
        data_dir: Path,
        **kwargs: Any,
    ) -> None:
        super().__init__(retroarch_binary, content_path, data_dir / "saves" / "ps1", **kwargs)
        self.core_path = Path(core_path)
        self.config_dir = Path(data_dir) / "retroarch"
        self._log_handle: IO[bytes] | None = None

    def _write_config(self) -> Path:
        self.config_dir.mkdir(parents=True, exist_ok=True)
        system_dir = self.config_dir / "system"
        states_dir = self.config_dir / "states"
        system_dir.mkdir(exist_ok=True)
        states_dir.mkdir(exist_ok=True)
        core_options = self.config_dir / "core-options.cfg"
        core_options.write_text(
            'pcsx_rearmed_gpu_thread_rendering = "sync"\n'
            'pcsx_rearmed_neon_enhancement_enable = "disabled"\n'
            'pcsx_rearmed_async_cd = "async"\n',
            encoding="utf-8",
        )
        config = self.config_dir / "retroarch.cfg"
        values = {
            "video_driver": "gl",
            "video_context_driver": "kms",
            "video_fullscreen": "true",
            "video_windowed_fullscreen": "true",
            "video_force_aspect": "true",
            "video_scale_integer": "false",
            "video_smooth": "false",
            "video_threaded": "true",
            "audio_driver": "alsa",
            "audio_device": "usb_output",
            "audio_latency": "128",
            "input_driver": "udev",
            "input_joypad_driver": "udev",
            "input_autodetect_enable": "true",
            # Linux xpad/Xbox layout.  Keeping this in the private config makes
            # the bundled RetroArch usable without the large assets package.
            "input_player1_joypad_index": "0",
            "input_player1_b_btn": "0",
            "input_player1_a_btn": "1",
            "input_player1_x_btn": "2",
            "input_player1_y_btn": "3",
            "input_player1_l_btn": "4",
            "input_player1_r_btn": "5",
            "input_player1_select_btn": "6",
            "input_player1_start_btn": "7",
            "input_player1_l3_btn": "9",
            "input_player1_r3_btn": "10",
            "input_player1_up_btn": "h0up",
            "input_player1_down_btn": "h0down",
            "input_player1_left_btn": "h0left",
            "input_player1_right_btn": "h0right",
            "input_player1_l2_axis": "+2",
            "input_player1_r2_axis": "+5",
            "savestate_directory": str(states_dir),
            "savefile_directory": str(self.saves_dir),
            "system_directory": str(system_dir),
            "core_options_path": str(core_options),
            "config_save_on_exit": "false",
            "pause_nonactive": "false",
        }
        config.write_text(
            "".join(f'{key} = "{value}"\n' for key, value in values.items()),
            encoding="utf-8",
        )
        return config

    def start(self) -> None:
        if self.process is not None and self.process.poll() is None:
            raise RuntimeError("session already running")
        ensure_ps1_runtime(self.mgba_binary, self.core_path)
        self.saves_dir.mkdir(parents=True, exist_ok=True)
        config = self._write_config()
        self._log_handle = (self.config_dir / "retroarch.log").open("ab")
        env = dict(os.environ)
        env["XDG_CONFIG_HOME"] = str(self.config_dir)
        try:
            self.process = subprocess.Popen(  # noqa: S603 - validated fixed executables
                [
                    *self.command_prefix,
                    str(self.mgba_binary),
                    "--config",
                    str(config),
                    "--fullscreen",
                    "--verbose",
                    "-L",
                    str(self.core_path),
                    str(self.rom_path),
                ],
                stdout=self._log_handle,
                stderr=subprocess.STDOUT,
                env=env,
                cwd=self.rom_path.parent,
            )
        except BaseException:
            self._log_handle.close()
            self._log_handle = None
            raise

    def _finalise(self) -> None:
        try:
            super()._finalise()
        finally:
            if self._log_handle is not None:
                self._log_handle.close()
                self._log_handle = None


def ensure_ps1_runtime(retroarch: Path, core: Path) -> tuple[Path, Path]:
    if not retroarch.is_file() or (os.name != "nt" and not os.access(retroarch, os.X_OK)):
        raise FileNotFoundError(f"RetroArch 不可用：{retroarch}")
    if not core.is_file():
        raise FileNotFoundError(f"PCSX-ReARMed 核心不可用：{core}")
    return retroarch, core
