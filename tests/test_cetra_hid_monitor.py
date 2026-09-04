import json
import subprocess

import pytest

from soundmonkey.monitors.cetra_hid import CetraHidMonitor


def _pw_payload(nodes):
    return json.dumps(nodes).encode()


def _make_sink(node_id, description):
    return {"id": node_id, "info": {"props": {
        "media.class": "Audio/Sink",
        "node.description": description,
    }}}


def _patch_pw_dump(monkeypatch, nodes):
    payload = _pw_payload(nodes)
    monkeypatch.setattr(subprocess, "check_output", lambda cmd, **kw: payload)


def test_sink_present_reports_ready(monkeypatch):
    _patch_pw_dump(monkeypatch, [
        _make_sink(99, "ROG CETRA TRUE WIRELESS SPEEDNOVA Analog Stereo"),
    ])
    m = CetraHidMonitor()
    connected = m._pw_monitor.check_once()
    assert connected is True


def test_sink_absent_reports_not_ready(monkeypatch):
    _patch_pw_dump(monkeypatch, [
        _make_sink(1, "Some Other Device"),
    ])
    m = CetraHidMonitor()
    connected = m._pw_monitor.check_once()
    assert connected is False


def test_custom_description_match(monkeypatch):
    _patch_pw_dump(monkeypatch, [
        _make_sink(1, "Some Other Device"),
        _make_sink(2, "ROG CETRA TRUE WIRELESS SPEEDNOVA Analog Stereo"),
    ])
    m = CetraHidMonitor(description_match="ROG CETRA")
    connected = m._pw_monitor.check_once()
    assert connected is True


def test_is_audio_ready_reflects_pw_state(monkeypatch):
    _patch_pw_dump(monkeypatch, [
        _make_sink(99, "ROG CETRA TRUE WIRELESS SPEEDNOVA Analog Stereo"),
    ])
    m = CetraHidMonitor()
    # Initially False before first check
    assert m.is_audio_ready() is False
    m._pw_monitor.check_once()
    assert m.is_audio_ready() is True


def test_is_audio_ready_updates_to_false_when_sink_disappears(monkeypatch):
    m = CetraHidMonitor()
    m._pw_monitor._connected = True
    assert m.is_audio_ready() is True
    _patch_pw_dump(monkeypatch, [])
    m._pw_monitor.check_once()
    assert m.is_audio_ready() is False


def test_battery_report_updates_state():
    m = CetraHidMonitor()
    data = bytes([0xcc, 0x12, 0x09, 0x00, 0x00, 100, 100, 50] + [0] * 56)
    handled = m._process_report(data)
    assert handled is True
    assert m.get_battery() == {"left": 100, "right": 100, "case": 50}


def test_non_battery_vendor_report_ignored():
    # Same report ID but a different subtype (e.g. the identity/connect blob)
    data = bytes([0xcc, 0x71, 0x02] + [0] * 61)
    m = CetraHidMonitor()
    handled = m._process_report(data)
    assert handled is False
    assert m.get_battery() is None


def test_short_report_ignored():
    # Consumer-control reports (report ID 12) are only 2 bytes
    data = bytes([0x0c, 0x08])
    m = CetraHidMonitor()
    handled = m._process_report(data)
    assert handled is False
    assert m.get_battery() is None


def test_battery_persists_until_next_report():
    m = CetraHidMonitor()
    m._process_report(bytes([0xcc, 0x12, 0x09, 0x00, 0x00, 80, 90, 40] + [0] * 56))
    assert m.get_battery() == {"left": 80, "right": 90, "case": 40}
    m._process_report(bytes([0xcc, 0x71, 0x02] + [0] * 61))
    assert m.get_battery() == {"left": 80, "right": 90, "case": 40}


def test_session_defaults_active_before_any_report(monkeypatch):
    # No HID event has been seen yet (e.g. daemon just started while the
    # earbuds were already out and in use) - assume active until told
    # otherwise, so a fresh start doesn't wrongly report "not ready".
    _patch_pw_dump(monkeypatch, [
        _make_sink(99, "ROG CETRA TRUE WIRELESS SPEEDNOVA Analog Stereo"),
    ])
    m = CetraHidMonitor()
    m._pw_monitor.check_once()
    assert m.is_audio_ready() is True


def test_power_off_report_clears_session_active():
    m = CetraHidMonitor()
    m._pw_monitor._connected = True
    assert m.is_audio_ready() is True
    handled = m._process_report(bytes([0xcc, 0x12, 0x01, 0x00, 0x00, 0x00, 0x00] + [0] * 57))
    assert handled is True
    assert m.is_audio_ready() is False


def test_connect_report_sets_session_active():
    m = CetraHidMonitor()
    m._pw_monitor._connected = True
    m._session_active = False
    m._process_report(bytes([0xcc, 0x12, 0x01, 0x00, 0x00, 0x11, 0x00] + [0] * 57))
    assert m.is_audio_ready() is True


def test_is_audio_ready_false_when_docked_even_if_sink_present(monkeypatch):
    # This is the actual bug: the sink persists as long as the dongle is
    # plugged in, regardless of whether the earbuds are docked. Session
    # tracking is what lets is_audio_ready() go false once they're put away.
    _patch_pw_dump(monkeypatch, [
        _make_sink(99, "ROG CETRA TRUE WIRELESS SPEEDNOVA Analog Stereo"),
    ])
    m = CetraHidMonitor()
    m._pw_monitor.check_once()
    assert m.is_audio_ready() is True
    m._process_report(bytes([0xcc, 0x12, 0x01, 0x00, 0x00, 0x00, 0x00] + [0] * 57))
    assert m.is_audio_ready() is False
    # Sink is still there (dongle still plugged in) - confirms it's the
    # session flag, not the pw check, that changed.
    assert m._pw_monitor.is_audio_ready() is True


def test_start_starts_both_pw_monitor_and_hid_thread(monkeypatch):
    pw_started = []
    hid_started = []
    m = CetraHidMonitor()
    monkeypatch.setattr(m._pw_monitor, "start", lambda: pw_started.append(True))
    monkeypatch.setattr(m._hid_thread, "start", lambda: hid_started.append(True))
    m.start()
    assert pw_started == [True]
    assert hid_started == [True]


def test_stop_stops_both_pw_monitor_and_hid_loop(monkeypatch):
    pw_stopped = []
    m = CetraHidMonitor()
    monkeypatch.setattr(m._pw_monitor, "stop", lambda: pw_stopped.append(True))
    m.stop()
    assert pw_stopped == [True]
    assert m._stop_event.is_set() is True
