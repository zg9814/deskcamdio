"""RaspberryPiSystem probes with subprocess calls faked out."""

from __future__ import annotations

import pytest

from deskcamdio.platform.system import RaspberryPiSystem


@pytest.fixture()
def pi(monkeypatch: pytest.MonkeyPatch) -> RaspberryPiSystem:
    sysctl = RaspberryPiSystem()
    calls: list[list[str]] = []
    responses: dict[tuple[str, ...], tuple[int, str]] = {}

    def fake_run(cmd, timeout=6.0):  # noqa: ANN001
        calls.append(cmd)
        return responses.get(tuple(cmd), (0, ""))

    monkeypatch.setattr("deskcamdio.platform.system._run", fake_run)
    monkeypatch.setattr("deskcamdio.platform.system._which", lambda name: "/usr/bin/" + name)
    sysctl.calls = calls  # type: ignore[attr-defined]
    sysctl.responses = responses  # type: ignore[attr-defined]
    return sysctl


def test_wifi_status_connected(pi: RaspberryPiSystem) -> None:
    pi.responses[("nmcli", "-t", "-f", "GENERAL,IP4", "device", "show", "wlan0")] = (
        0,
        "GENERAL.STATE:connected\nGENERAL.CONNECTION:home-wifi",
    )
    status = pi.wifi_status()
    assert status["connected"] is True
    assert status["ssid"] == "home-wifi"


def test_wifi_status_disconnected_when_nmcli_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("deskcamdio.platform.system._which", lambda _n: None)
    sysctl = RaspberryPiSystem()
    assert sysctl.wifi_status()["connected"] is False


def test_wifi_reconnect_activates_first_connection(pi: RaspberryPiSystem) -> None:
    pi.responses[("nmcli", "-t", "-f", "NAME", "connection", "show", "--active")] = (
        0,
        "home-wifi\nsecond",
    )
    pi.responses[("nmcli", "connection", "up", "home-wifi")] = (0, "")
    assert pi.wifi_reconnect() is True


def test_bluetooth_status_parses_flags(pi: RaspberryPiSystem) -> None:
    pi.responses[("bluetoothctl", "show")] = (
        0,
        "Powered: yes\nDiscoverable: yes",
    )
    pi.responses[("bluetoothctl", "devices", "Connected")] = (0, "Device 1\nDevice 2")
    status = pi.bluetooth_status()
    assert status == {"powered": True, "discoverable": True, "devices": 2}


def test_bluetooth_toggle_powers_off(pi: RaspberryPiSystem) -> None:
    pi.responses[("bluetoothctl", "show")] = (0, "Powered: yes\nDiscoverable: no")
    assert pi.bluetooth_toggle() is True  # power off command succeeded
    # Simulate controller state after the toggle:
    pi.responses[("bluetoothctl", "show")] = (0, "Powered: no\nDiscoverable: no")
    assert pi.bluetooth_status()["powered"] is False


def test_bluetooth_controller_scan_prefers_gamepads(pi: RaspberryPiSystem) -> None:
    pi.responses[("bluetoothctl", "devices")] = (
        0,
        "Device AA:BB:CC:DD:EE:01 Living Room TV\nDevice AA:BB:CC:DD:EE:02 8BitDo Controller",
    )
    pi.responses[("bluetoothctl", "info", "AA:BB:CC:DD:EE:02")] = (
        0,
        "Connected: no",
    )
    found = pi.bluetooth_scan_controllers()
    assert found == [
        {
            "address": "AA:BB:CC:DD:EE:02",
            "name": "8BitDo Controller",
            "connected": False,
        }
    ]


def test_bluetooth_controller_pair_trust_connect(pi: RaspberryPiSystem) -> None:
    address = "AA:BB:CC:DD:EE:02"
    pi.responses[("bluetoothctl", "info", address)] = (0, "Paired: no")
    assert pi.bluetooth_connect_controller(address) is True
    assert ["bluetoothctl", "trust", address] in pi.calls
    assert ["bluetoothctl", "connect", address] in pi.calls
    assert pi.bluetooth_connect_controller("not-an-address") is False


def test_set_volume_targets_usb_card_then_pcm(pi: RaspberryPiSystem) -> None:
    assert pi.set_system_volume(50) is True
    assert pi.calls[-1][-4:] == ["1", "set", "Speaker", "50%"]

    pi.responses.clear()
    first_key = ("amixer", "-c", "1", "set", "Speaker", "30%")
    second_key = ("amixer", "-c", "1", "set", "PCM", "30%")
    del first_key, second_key
    # Simulate Master failing: _run returns rc=1 for everything except PCM.

    original_responses = pi.responses

    def selective(cmd, timeout=6.0):  # noqa: ANN001
        if "Speaker" in cmd:
            return 1, ""
        original_responses[tuple(cmd)] = (0, "")
        return (0, "")

    pi_module_run = type(pi).__mro__  # keep linters quiet
    del pi_module_run
    import deskcamdio.platform.system as system_mod

    saved = system_mod._run
    system_mod._run = selective  # type: ignore[assignment]
    try:
        assert pi.set_system_volume(30) is True
    finally:
        system_mod._run = saved


def test_brightness_without_backlight_returns_false(
    pi: RaspberryPiSystem, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(RaspberryPiSystem, "_backlight_file", lambda _self: None)
    assert pi.get_brightness() == 80
    assert pi.set_brightness(50) is False
