import json
import subprocess

import pytest

from soundmonkey.monitors.arctis_monitor import ArctisMonitor


def _hs_payload(devices):
    return json.dumps({"name": "HeadsetControl", "devices": devices}).encode()


def _patch_hs_output(monkeypatch, payload):
    monkeypatch.setattr(subprocess, "check_output", lambda cmd, **kw: payload)


def test_connected_success_with_battery(monkeypatch):
    _patch_hs_output(monkeypatch, _hs_payload([
        {"status": "success", "device": "SteelSeries Arctis Pro Wireless",
         "battery": {"status": "BATTERY_AVAILABLE", "level": 85}},
    ]))
    m = ArctisMonitor()
    m._poll_once()
    assert m.is_audio_ready() is True
    assert m.get_battery() == 85


def test_partial_status_timeout_not_connected(monkeypatch):
    # A battery request timeout is consistent with the headset genuinely
    # being off (base station has no RF link to poll). NOT connected.
    _patch_hs_output(monkeypatch, _hs_payload([
        {"status": "partial", "device": "SteelSeries Arctis Pro Wireless",
         "errors": {"battery": "Battery status request timed out"}},
    ]))
    m = ArctisMonitor()
    m._poll_once()
    assert m.is_audio_ready() is False
    assert m.get_battery() is None


def test_partial_status_offline_not_connected(monkeypatch):
    # Real headsetcontrol output observed with the headset powered off:
    # base station present, headset itself unreachable. NOT connected.
    _patch_hs_output(monkeypatch, _hs_payload([
        {"status": "partial", "device": "SteelSeries Arctis Pro Wireless",
         "errors": {"battery": "Device is offline or not responding"}},
    ]))
    m = ArctisMonitor()
    m._poll_once()
    assert m.is_audio_ready() is False
    assert m.get_battery() is None


def test_partial_status_hid_error_still_connected(monkeypatch):
    # Real headsetcontrol output observed with the headset genuinely on and
    # streaming audio: only the battery telemetry glitched. Still connected,
    # with battery reported as unavailable rather than a stale/wrong value.
    _patch_hs_output(monkeypatch, _hs_payload([
        {"status": "partial", "device": "SteelSeries Arctis Pro Wireless",
         "battery": {"status": "BATTERY_UNAVAILABLE", "level": -1},
         "errors": {"battery": "HID communication error"}},
    ]))
    m = ArctisMonitor()
    m._poll_once()
    assert m.is_audio_ready() is True
    assert m.get_battery() == -1


def test_unavailable_status_not_connected(monkeypatch):
    _patch_hs_output(monkeypatch, _hs_payload([
        {"status": "unavailable", "device": "SteelSeries Arctis Pro Wireless"},
    ]))
    m = ArctisMonitor()
    m._poll_once()
    assert m.is_audio_ready() is False


def test_no_devices(monkeypatch):
    _patch_hs_output(monkeypatch, _hs_payload([]))
    m = ArctisMonitor()
    m._poll_once()
    assert m.is_audio_ready() is False


def test_wrong_device_not_connected(monkeypatch):
    _patch_hs_output(monkeypatch, _hs_payload([
        {"status": "success", "device": "Some Other Headset",
         "battery": {"status": "BATTERY_AVAILABLE", "level": 50}},
    ]))
    m = ArctisMonitor()
    m._poll_once()
    assert m.is_audio_ready() is False


def test_timeout_marks_not_connected(monkeypatch):
    def raise_timeout(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 10)

    monkeypatch.setattr(subprocess, "check_output", raise_timeout)
    m = ArctisMonitor()
    # pre-set a connected state to ensure it gets cleared
    m.state.connected = True
    m._poll_once()
    assert m.is_audio_ready() is False
    assert m.get_battery() is None


def test_malformed_json_marks_not_connected(monkeypatch):
    monkeypatch.setattr(subprocess, "check_output", lambda cmd, **kw: b"not json")
    m = ArctisMonitor()
    m._poll_once()
    assert m.is_audio_ready() is False


def test_description_match_filter(monkeypatch):
    _patch_hs_output(monkeypatch, _hs_payload([
        {"status": "success", "device": "Arctis Pro Wireless Game"},
        {"status": "success", "device": "SteelSeries Arctis Pro Wireless",
         "battery": {"status": "BATTERY_AVAILABLE", "level": 42}},
    ]))
    m = ArctisMonitor(description_match="SteelSeries Arctis Pro Wireless")
    m._poll_once()
    assert m.is_audio_ready() is True
    assert m.get_battery() == 42
