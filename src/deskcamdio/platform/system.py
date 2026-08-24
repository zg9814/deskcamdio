"""System control adapters: Wi-Fi/BT/brightness/volume per platform."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any


class SystemControlBase:
    """Shared shape; subclasses override the probes that can work locally."""

    def wifi_status(self) -> dict[str, Any]:
        raise NotImplementedError

    def wifi_reconnect(self) -> bool:
        raise NotImplementedError

    def bluetooth_status(self) -> dict[str, Any]:
        raise NotImplementedError

    def bluetooth_toggle(self) -> bool:
        raise NotImplementedError

    def bluetooth_scan_controllers(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    def bluetooth_connect_controller(self, address: str) -> bool:
        raise NotImplementedError

    def get_brightness(self) -> int:
        raise NotImplementedError

    def set_brightness(self, percent: int) -> bool:
        raise NotImplementedError

    def set_system_volume(self, percent: int) -> bool:
        raise NotImplementedError


def _run(cmd: list[str], timeout: float = 6.0) -> tuple[int, str]:
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argv
            cmd, capture_output=True, text=True, check=False, timeout=timeout
        )
        return proc.returncode, (proc.stdout + proc.stderr).strip()
    except (OSError, subprocess.TimeoutExpired):
        return 127, ""


def _which(name: str) -> str | None:
    return shutil.which(name)


class SimulatedSystem(SystemControlBase):
    """Deterministic stand-in for Windows dev and CI."""

    def __init__(self) -> None:
        self.wifi = {"connected": True, "ssid": "SimNet", "ip": "10.0.0.2"}
        self.bluetooth = {"powered": True, "discoverable": False, "devices": 0}
        self.controllers = [
            {"address": "00:11:22:33:44:55", "name": "Fish Test Gamepad", "connected": False}
        ]
        self.brightness = 80

    def wifi_status(self) -> dict[str, Any]:
        return dict(self.wifi)

    def wifi_reconnect(self) -> bool:
        self.wifi["connected"] = True
        return True

    def bluetooth_status(self) -> dict[str, Any]:
        return dict(self.bluetooth)

    def bluetooth_toggle(self) -> bool:
        powered = not bool(self.bluetooth["powered"])
        self.bluetooth["powered"] = powered
        return powered

    def bluetooth_scan_controllers(self) -> list[dict[str, Any]]:
        return [dict(controller) for controller in self.controllers]

    def bluetooth_connect_controller(self, address: str) -> bool:
        for controller in self.controllers:
            if controller["address"] == address:
                controller["connected"] = True
                self.bluetooth["devices"] = 1
                return True
        return False

    def get_brightness(self) -> int:
        return self.brightness

    def set_brightness(self, percent: int) -> bool:
        self.brightness = max(5, min(100, int(percent)))
        return True

    def set_system_volume(self, percent: int) -> bool:
        return True


class RaspberryPiSystem(SystemControlBase):
    """nmcli / bluetoothctl / amixer / sysfs backlight."""

    BACKLIGHT_GLOBS = (
        "/sys/class/backlight/*/brightness",
        "/sys/devices/platform/rpi-backlight/backlight/*/brightness",
    )

    # ---- Wi-Fi -------------------------------------------------------------

    def wifi_status(self) -> dict[str, Any]:
        if _which("nmcli") is None:
            return {"connected": False, "ssid": "", "ip": ""}
        rc, out = _run(["nmcli", "-t", "-f", "GENERAL,IP4", "device", "show", "wlan0"])
        connected = rc == 0 and "connected" in out
        ssid = ""
        for line in out.splitlines():
            if line.startswith("GENERAL.CONNECTION:") and line.endswith("--"):
                continue
            if line.startswith("GENERAL.CONNECTION:"):
                ssid = line.split(":", 1)[1]
        rc_ip, ip_out = _run(["hostname", "-I"])
        ip = ip_out.split()[0] if rc_ip == 0 and ip_out else ""
        return {"connected": connected, "ssid": ssid, "ip": ip}

    def wifi_reconnect(self) -> bool:
        rc, _out = _run(["nmcli", "networking", "connectivity", "check"])
        if rc != 0:
            return False
        rc2, out2 = _run(["nmcli", "-t", "-f", "NAME", "connection", "show", "--active"])
        if rc2 != 0 or not out2:
            return False
        first = out2.splitlines()[0]
        rc3, _ = _run(["nmcli", "connection", "up", first])
        return rc3 == 0

    # ---- Bluetooth ---------------------------------------------------------

    def bluetooth_status(self) -> dict[str, Any]:
        if _which("bluetoothctl") is None:
            return {"powered": False, "discoverable": False, "devices": 0}
        rc, out = _run(["bluetoothctl", "show"])
        powered = "Powered: yes" in out
        discoverable = "Discoverable: yes" in out
        rc_d, devices_out = _run(["bluetoothctl", "devices", "Connected"])
        count = len(devices_out.splitlines()) if rc_d == 0 else 0
        return {"powered": powered, "discoverable": discoverable, "devices": count}

    def bluetooth_toggle(self) -> bool:
        if _which("bluetoothctl") is None:
            return False
        status = self.bluetooth_status()
        target = "off" if status["powered"] else "on"
        rc, _out = _run(["bluetoothctl", "power", target])
        return rc == 0

    def bluetooth_scan_controllers(self) -> list[dict[str, Any]]:
        if _which("bluetoothctl") is None:
            return []
        bluetoothctl = "bluetoothctl"
        _run([bluetoothctl, "power", "on"])
        _run([bluetoothctl, "pairable", "on"])
        _run([bluetoothctl, "--timeout", "8", "scan", "on"], timeout=10.0)
        rc, out = _run([bluetoothctl, "devices"])
        if rc != 0:
            return []
        candidates: list[dict[str, Any]] = []
        preferred: list[dict[str, Any]] = []
        tags = ("gamepad", "controller", "joystick", "xbox", "dualshock", "dualsense", "8bitdo")
        for line in out.splitlines():
            parts = line.split(maxsplit=2)
            if len(parts) != 3 or parts[0] != "Device":
                continue
            address, name = parts[1], parts[2]
            info_rc, info = _run([bluetoothctl, "info", address], timeout=3.0)
            item = {
                "address": address,
                "name": name,
                "connected": info_rc == 0 and "Connected: yes" in info,
            }
            candidates.append(item)
            if any(tag in name.lower() for tag in tags):
                preferred.append(item)
        return (preferred or candidates)[:3]

    def bluetooth_connect_controller(self, address: str) -> bool:
        if (
            _which("bluetoothctl") is None
            or re.fullmatch(r"(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}", address) is None
        ):
            return False
        bluetoothctl = "bluetoothctl"
        info_rc, info = _run([bluetoothctl, "info", address], timeout=3.0)
        paired = info_rc == 0 and "Paired: yes" in info
        if not paired:
            pair_rc, _ = _run(
                [bluetoothctl, "--agent", "NoInputNoOutput", "pair", address], timeout=20.0
            )
            if pair_rc != 0:
                return False
        _run([bluetoothctl, "trust", address], timeout=4.0)
        connect_rc, _ = _run([bluetoothctl, "connect", address], timeout=12.0)
        return connect_rc == 0

    # ---- Brightness ----------------------------------------------------------

    def _backlight_file(self) -> Path | None:
        for pattern in self.BACKLIGHT_GLOBS:
            matches = [p for p in Path("/").glob(pattern.lstrip("/"))] if "*" in pattern else []
            for match in sorted(matches):
                max_file = match.parent / "max_brightness"
                try:
                    int(max_file.read_text().strip())
                except (OSError, ValueError):
                    continue
                return match
        return None

    def get_brightness(self) -> int:
        bl = self._backlight_file()
        if bl is None:
            return 80
        try:
            cur = int(bl.read_text().strip())
            mx = int((bl.parent / "max_brightness").read_text().strip())
            return round(cur * 100 / mx)
        except (OSError, ValueError, ZeroDivisionError):
            return 80

    def set_brightness(self, percent: int) -> bool:
        bl = self._backlight_file()
        if bl is None:
            return False
        percent = max(5, min(100, int(percent)))
        try:
            mx = int((bl.parent / "max_brightness").read_text().strip())
            bl.write_text(str(round(mx * percent / 100)))
            return True
        except OSError:
            return False

    # ---- Volume ----------------------------------------------------------------

    def set_system_volume(self, percent: int) -> bool:
        amixer = _which("amixer")
        if amixer is None:
            return False
        percent = max(0, min(100, int(percent)))
        card = os.getenv("DESKCAMDIO_ALSA_CARD", "1")
        control = os.getenv("DESKCAMDIO_ALSA_CONTROL", "Speaker")
        rc, _out = _run([amixer, "-c", card, "set", control, f"{percent}%"], timeout=3.0)
        if rc != 0:
            rc2, _o2 = _run([amixer, "-c", card, "set", "PCM", f"{percent}%"], timeout=3.0)
            return rc2 == 0
        return True


def create_system_control() -> SystemControlBase:
    if os.getenv("DESKCAMDIO_PLATFORM") == "raspberry_pi":
        return RaspberryPiSystem()
    return SimulatedSystem()
