import json
import subprocess

from soundmonkey.monitors.pipewire import PipewirePresenceMonitor


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
