import json
import subprocess

from soundmonkey.monitors.pipewire import PipewirePresenceMonitor


def _pw_payload(nodes):
    return json.dumps(nodes).encode()


def _make_sink(node_id, description, bluez_address=None):
    props = {
        "media.class": "Audio/Sink",
        "node.description": description,
    }
    if bluez_address is not None:
        props["api.bluez5.address"] = bluez_address
    return {"id": node_id, "info": {"props": props}}


def _patch_pw_dump(monkeypatch, nodes):
    payload = _pw_payload(nodes)
    monkeypatch.setattr(subprocess, "check_output", lambda cmd, **kw: payload)


def test_sink_present_reports_ready(monkeypatch):
    _patch_pw_dump(monkeypatch, [_make_sink(1, "WF-1000XM5")])
    m = PipewirePresenceMonitor(description_match="WF-1000XM5")
    assert m.check_once() is True
    assert m.is_audio_ready() is True


def test_sink_absent_reports_not_ready(monkeypatch):
    _patch_pw_dump(monkeypatch, [_make_sink(1, "Some Other Device")])
    m = PipewirePresenceMonitor(description_match="WF-1000XM5")
    assert m.check_once() is False
    assert m.is_audio_ready() is False


def test_non_sink_media_class_ignored(monkeypatch):
    # A Source with a matching description shouldn't count as a Sink.
    _patch_pw_dump(monkeypatch, [{"id": 1, "info": {"props": {
        "media.class": "Audio/Source", "node.description": "WF-1000XM5",
    }}}])
    m = PipewirePresenceMonitor(description_match="WF-1000XM5")
    assert m.check_once() is False


def test_empty_pw_dump_reports_not_ready(monkeypatch):
    _patch_pw_dump(monkeypatch, [])
    m = PipewirePresenceMonitor(description_match="WF-1000XM5")
    assert m.check_once() is False


def test_timeout_reports_not_ready(monkeypatch):
    def raise_timeout(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 2)

    monkeypatch.setattr(subprocess, "check_output", raise_timeout)
    m = PipewirePresenceMonitor(description_match="WF-1000XM5")
    assert m.check_once() is False


def test_malformed_json_reports_not_ready(monkeypatch):
    monkeypatch.setattr(subprocess, "check_output", lambda cmd, **kw: b"not json")
    m = PipewirePresenceMonitor(description_match="WF-1000XM5")
    assert m.check_once() is False


def test_custom_description_match(monkeypatch):
    _patch_pw_dump(monkeypatch, [
        _make_sink(1, "Some Other Device"),
        _make_sink(2, "Arctis Pro Wireless Analog Stereo"),
    ])
    m = PipewirePresenceMonitor(description_match="Arctis Pro Wireless")
    assert m.check_once() is True


def test_is_audio_ready_before_first_check_defaults_false():
    m = PipewirePresenceMonitor(description_match="WF-1000XM5")
    assert m.is_audio_ready() is False


def test_is_audio_ready_updates_to_false_when_sink_disappears(monkeypatch):
    _patch_pw_dump(monkeypatch, [_make_sink(1, "WF-1000XM5")])
    m = PipewirePresenceMonitor(description_match="WF-1000XM5")
    m.check_once()
    assert m.is_audio_ready() is True

    _patch_pw_dump(monkeypatch, [])
    m.check_once()
    assert m.is_audio_ready() is False


def test_get_battery_unsupported():
    m = PipewirePresenceMonitor(description_match="WF-1000XM5")
    assert m.get_battery() is None


def _patch_pw_and_bluetoothctl(monkeypatch, nodes, bluetoothctl_output, expected_mac=None):
    pw_payload = _pw_payload(nodes)
    calls = []

    def fake_check_output(cmd, **kw):
        calls.append(cmd)
        if cmd[0] == "bluetoothctl":
            if expected_mac is not None:
                assert cmd == ["bluetoothctl", "info", expected_mac]
            return bluetoothctl_output
        return pw_payload

    monkeypatch.setattr(subprocess, "check_output", fake_check_output)
    return calls


def test_no_bluez_address_on_matched_sink_never_calls_bluetoothctl(monkeypatch):
    # A USB device (or any sink PipeWire doesn't tag as bluez5) has no
    # api.bluez5.address prop to auto-detect, and no explicit mac_address
    # was given either - battery should never be queried.
    calls = _patch_pw_and_bluetoothctl(monkeypatch, [_make_sink(1, "WF-1000XM5")], b"")
    m = PipewirePresenceMonitor(description_match="WF-1000XM5")
    m.check_once()
    assert all(cmd[0] != "bluetoothctl" for cmd in calls)
    assert m.get_battery() is None


def test_battery_auto_detected_from_matched_sink_address(monkeypatch):
    # No mac_address given - the address comes straight from the matched
    # sink's own api.bluez5.address prop, same as PipeWire already reports.
    _patch_pw_and_bluetoothctl(
        monkeypatch,
        [_make_sink(1, "WF-1000XM5", bluez_address="AC:80:0A:29:4D:FE")],
        b"Battery Percentage: 0x64 (100)\n",
        expected_mac="AC:80:0A:29:4D:FE",
    )
    m = PipewirePresenceMonitor(description_match="WF-1000XM5")
    m.check_once()
    assert m.get_battery() == 100


def test_explicit_mac_address_overrides_detected_one(monkeypatch):
    _patch_pw_and_bluetoothctl(
        monkeypatch,
        [_make_sink(1, "WF-1000XM5", bluez_address="AC:80:0A:29:4D:FE")],
        b"Battery Percentage: 0x32 (50)\n",
        expected_mac="11:22:33:44:55:66",
    )
    m = PipewirePresenceMonitor(
        description_match="WF-1000XM5", mac_address="11:22:33:44:55:66",
    )
    m.check_once()
    assert m.get_battery() == 50


def test_detected_address_persists_when_sink_briefly_disappears(monkeypatch):
    _patch_pw_and_bluetoothctl(
        monkeypatch,
        [_make_sink(1, "WF-1000XM5", bluez_address="AC:80:0A:29:4D:FE")],
        b"Battery Percentage: 0x64 (100)\n",
    )
    m = PipewirePresenceMonitor(description_match="WF-1000XM5")
    m.check_once()
    assert m.get_battery() == 100

    # Sink momentarily gone (e.g. a transport flap), but battery should
    # still be answerable from the address learned on the previous poll.
    calls = _patch_pw_and_bluetoothctl(
        monkeypatch, [], b"Battery Percentage: 0x5a (90)\n",
        expected_mac="AC:80:0A:29:4D:FE",
    )
    m.check_once()
    assert m.is_audio_ready() is False
    assert m.get_battery() == 90
    assert any(cmd[0] == "bluetoothctl" for cmd in calls)


def test_get_battery_missing_percentage_line_is_none(monkeypatch):
    _patch_pw_and_bluetoothctl(
        monkeypatch,
        [_make_sink(1, "WF-1000XM5", bluez_address="AC:80:0A:29:4D:FE")],
        b"Name: WF-1000XM5\nConnected: yes\n",
    )
    m = PipewirePresenceMonitor(description_match="WF-1000XM5")
    m.check_once()
    assert m.get_battery() is None


def test_get_battery_bluetoothctl_error_is_none(monkeypatch):
    def fake_check_output(cmd, **kw):
        if cmd[0] == "bluetoothctl":
            raise subprocess.CalledProcessError(1, cmd)
        return _pw_payload([_make_sink(1, "WF-1000XM5", bluez_address="AC:80:0A:29:4D:FE")])

    monkeypatch.setattr(subprocess, "check_output", fake_check_output)
    m = PipewirePresenceMonitor(description_match="WF-1000XM5")
    m.check_once()
    assert m.get_battery() is None
    assert m.is_audio_ready() is True  # presence check unaffected by battery failure


def test_get_battery_bluetoothctl_timeout_is_none(monkeypatch):
    def fake_check_output(cmd, **kw):
        if cmd[0] == "bluetoothctl":
            raise subprocess.TimeoutExpired(cmd, 2)
        return _pw_payload([_make_sink(1, "WF-1000XM5", bluez_address="AC:80:0A:29:4D:FE")])

    monkeypatch.setattr(subprocess, "check_output", fake_check_output)
    m = PipewirePresenceMonitor(description_match="WF-1000XM5")
    m.check_once()
    assert m.get_battery() is None
