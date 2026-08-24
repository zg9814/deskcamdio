"""GBA game session: mGBA process lifecycle, .sav durability, exit combos."""

from __future__ import annotations

import contextlib
import logging
import os
import shutil
import signal
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)

GRACEFUL_EXIT_SECONDS = 3.0
KILL_AFTER_SECONDS = 1.0
SHOULDER_COMBO = {"L1", "R1", "L2", "R2"}
COMBO_HOLD_SECONDS = 1.0


class GameSession:
    """Owns exactly one mGBA child process per play round."""

    def __init__(
        self,
        mgba_binary: Path,
        rom_path: Path,
        saves_dir: Path,
        *,
        controller_config: str = "",
        on_exit: Callable[[str], None] | None = None,
        command_prefix: list[str] | None = None,
    ) -> None:
        self.mgba_binary = Path(mgba_binary)
        self.rom_path = Path(rom_path)
        self.saves_dir = Path(saves_dir) / self._sav_key()
        self.controller_config = controller_config
        self.command_prefix = command_prefix or []
        self.on_exit = on_exit or (lambda _reason: None)
        self.process: subprocess.Popen[bytes] | None = None
        self.exit_reason = ""

    def _sav_key(self) -> str:
        import hashlib

        return hashlib.sha256(str(self.rom_path).encode()).hexdigest()[:16]

    # ---- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        if self.process is not None and self.process.poll() is None:
            raise RuntimeError("session already running")
        env = dict(os.environ)
        if self.controller_config:
            env["SDL_GAMECONTROLLERCONFIG"] = self.controller_config
        self.saves_dir.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
        # mGBA CLI (mgba.6): -C overrides config keys; general.savegamePath
        # routes .sav files into the per-ROM directory. cwd is also pinned so
        # relative artifacts land in the same sandbox.
        self.process = subprocess.Popen(  # noqa: S603 - fixed argv from trusted config
            [
                *self.command_prefix,
                str(self.mgba_binary),
                "-C",
                f"general.savegamePath={self.saves_dir}",
                str(self.rom_path),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
            cwd=self.saves_dir,
        )
        LOGGER.info(
            "event=game_started rom_sha=%s pid=%s duration_ms=%d",
            self._sav_key(),
            self.process.pid,
            round((time.monotonic() - started) * 1000),
        )

    def request_stop(self, reason: str) -> None:
        """Graceful stop: SIGTERM → 3 s wait → kill after another second."""
        if self.process is None:
            return
        self.exit_reason = reason
        with contextlib.suppress(ProcessLookupError):
            self.process.send_signal(signal.SIGTERM)
        try:
            self.process.wait(timeout=GRACEFUL_EXIT_SECONDS)
        except subprocess.TimeoutExpired:
            LOGGER.warning("mGBA ignored terminate; killing")
            self.process.kill()
            try:
                self.process.wait(timeout=KILL_AFTER_SECONDS)
            except subprocess.TimeoutExpired:  # pragma: no cover - kill rarely hangs
                LOGGER.error("event=game_stop_failed")
        self._finalise()

    def poll(self) -> bool:
        """True when the child has exited on its own; finalises state."""
        if self.process is None:
            return False
        if self.process.poll() is None:
            return False
        self.exit_reason = "self-exit"
        self._finalise()
        return True

    def _finalise(self) -> None:
        assert self.process is not None
        exit_code = self.process.returncode
        # Durability: fsync the save directory so .sav survives power loss.
        # (POSIX-only; Windows cannot open directories.)
        if os.name == "posix":
            try:
                dir_fd = os.open(self.saves_dir, os.O_RDONLY)
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
            except OSError:  # pragma: no cover - filesystem without dir fsync
                LOGGER.warning("event=sav_fsync_skipped")
        LOGGER.info("event=game_stopped reason=%s exit_code=%s", self.exit_reason, exit_code)
        process = self.process
        self.process = None
        del process
        self.on_exit(self.exit_reason or "unknown")

    @property
    def running(self) -> bool:
        return self.process is not None and self.process.poll() is None


class ControllerMonitor:
    """evdev bypass listener for the four-shoulder exit combo.

    Falls back to a no-op monitor where evdev is unavailable (Windows dev),
    so GameSession stays testable end-to-end.
    """

    def __init__(self, session: GameSession, devices: Any = None) -> None:
        self.session = session
        self.stop_flag = threading.Event()
        self.held_since: float | None = None
        self.devices = devices
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self.stop_flag.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="pad-combo")
        self._thread.start()

    @staticmethod
    def _button_of(event: Any) -> str | None:
        import evdev

        if event.type != evdev.ecodes.EV_KEY:
            return None
        name = {**evdev.ecodes.KEY}.get(event.code, "")
        return {
            "KEY_LEFTSHOULDER": "L1",
            "KEY_RIGHTSHOULDER": "R1",
            "KEY_LEFTTRIGGER": "L2",
            "KEY_RIGHTTRIGGER": "R2",
            "BTN_TL": "L1",
            "BTN_TR": "R1",
            "BTN_TL2": "L2",
            "BTN_TR2": "R2",
        }.get(name)

    def _update_combo(self, held: set[str], button: str, value: int) -> None:
        if value == 1:
            held.add(button)
        elif value == 0:
            held.discard(button)
        now = time.monotonic()
        if held == SHOULDER_COMBO:
            if self.held_since is None:
                self.held_since = now
            elif now - self.held_since >= COMBO_HOLD_SECONDS:
                self.session.request_stop("shoulder-combo")
                self.stop_flag.set()
        else:
            self.held_since = None

    def _loop(self) -> None:  # noqa: C901  # pragma: no cover - hardware loop
        import select

        try:
            import evdev
        except ImportError:
            LOGGER.info("event=controller_monitor_disabled reason=evdev-unavailable")
            return

        held: set[str] = set()
        devices: dict[int, Any] = {}
        while not self.stop_flag.wait(0.1):
            if self.devices is not None and not devices:
                devices = {device.fd: device for device in self.devices}
            elif self.devices is None:
                known = {device.path for device in devices.values()}
                for path in evdev.list_devices():
                    if path not in known:
                        with contextlib.suppress(OSError):
                            device = evdev.InputDevice(path)
                            devices[device.fd] = device
            if not devices:
                continue
            readable, _, _ = select.select(list(devices), [], [], 0.1)
            for fd in readable:
                device = devices.get(fd)
                if device is None:
                    continue
                try:
                    events = device.read()
                except OSError:
                    devices.pop(fd, None)
                    continue
                for event in events:
                    button = self._button_of(event)
                    if button is not None:
                        self._update_combo(held, button, event.value)

    def stop(self) -> None:
        self.stop_flag.set()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=0.5)
        self._thread = None


def ensure_mgba(binary_path: Path) -> Path:
    """Validate the bundled binary exists and is executable."""
    if not binary_path.is_file():
        raise FileNotFoundError(f"mGBA binary missing at {binary_path}")
    if os.name != "nt" and not os.access(binary_path, os.X_OK):
        raise PermissionError(f"mGBA binary not executable: {binary_path}")
    return binary_path


def find_mgba() -> Path:
    candidates = [
        Path(__file__).resolve().parents[2] / "deploy" / "native" / "aarch64" / "mgba" / "mgba",
        Path("/opt/deskcamdio/current/deploy/native/aarch64/mgba/mgba"),
        Path("/usr/local/bin/mgba"),
    ]
    if shutil.which("mgba"):
        candidates.append(Path(shutil.which("mgba")))  # type: ignore[arg-type]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[0]
