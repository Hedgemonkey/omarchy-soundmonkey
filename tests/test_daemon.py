import json

from soundmonkey import daemon


class FakeMonitor:
    def __init__(self, ready, battery=None):
        self._ready = ready
        self._battery = battery

    def is_audio_ready(self):
        return self._ready


class FakeMonitorWithBattery(FakeMonitor):
    def get_battery(self):
        return self._battery


class FakeSinkManager:
    """Records calls and returns scripted results."""
    def __init__(self, sink_ok=True, source_ok=True, auto_ok=True, match_ok=True):
        self.calls = []
        self._sink_ok = sink_ok
        self._source_ok = source_ok
        self._auto_ok = auto_ok
        self._match_ok = match_ok

    def set_default_by_description_substr(self, substr):
        self.calls.append(("sink", substr))
        return self._sink_ok

    def set_default_source_by_description_substr(self, substr):
        self.calls.append(("source", substr))
        return self._source_ok

    def set_internal_auto(self):
        self.calls.append(("auto",))
        return self._auto_ok

    def set_internal_match(self, substr):
        self.calls.append(("match", substr))
        return self._match_ok


CFG = {
    "devices": {
        "WF1000XM5": {"sink_match": "WF-1000XM5", "source_match": "bluez_input"},
        "CETRA": {"sink_match": "ROG CETRA", "source_match": "ROG CETRA Mono"},
        "ARCTIS": {"sink_match": "Arctis Pro Wireless Analog Stereo",
                   "source_match": "Arctis Pro Wireless Mono",
                   "monitor_match": "Arctis Pro Wireless"},
    },
    "priority_order": ["WF1000XM5", "CETRA", "ARCTIS"],
    "fallback": {"mode": "system"},
}


def test_build_monitors_creates_all_three():
    monitors = daemon.build_monitors(CFG)
    assert set(monitors.keys()) == {"WF1000XM5", "CETRA", "ARCTIS"}
    from soundmonkey.monitors.pipewire import PipewirePresenceMonitor
    from soundmonkey.monitors.cetra_hid import CetraHidMonitor
    from soundmonkey.monitors.headsetcontrol import HeadsetControlMonitor
    assert isinstance(monitors["WF1000XM5"], PipewirePresenceMonitor)
    assert isinstance(monitors["CETRA"], CetraHidMonitor)
    assert isinstance(monitors["ARCTIS"], HeadsetControlMonitor)


def test_decide_choice_picks_highest_priority_ready():
    monitors = {
        "WF1000XM5": FakeMonitor(False),
        "CETRA": FakeMonitor(True),
        "ARCTIS": FakeMonitor(True),
    }
    assert daemon.decide_choice(monitors, ["WF1000XM5", "CETRA", "ARCTIS"]) == "CETRA"


def test_decide_choice_xm5_wins_over_all():
    monitors = {
        "WF1000XM5": FakeMonitor(True),
        "CETRA": FakeMonitor(True),
        "ARCTIS": FakeMonitor(True),
    }
    assert daemon.decide_choice(monitors, ["WF1000XM5", "CETRA", "ARCTIS"]) == "WF1000XM5"


def test_decide_choice_none_ready_returns_none():
    monitors = {
        "WF1000XM5": FakeMonitor(False),
        "CETRA": FakeMonitor(False),
        "ARCTIS": FakeMonitor(False),
    }
    assert daemon.decide_choice(monitors, ["WF1000XM5", "CETRA", "ARCTIS"]) is None


def test_decide_choice_respects_priority_order():
    # ARCTIS first in priority order, and ready -> should win even though
    # it's the "fallback" in the old hardcoded design.
    monitors = {
        "WF1000XM5": FakeMonitor(False),
        "CETRA": FakeMonitor(True),
        "ARCTIS": FakeMonitor(True),
    }
    order = ["ARCTIS", "WF1000XM5", "CETRA"]
    assert daemon.decide_choice(monitors, order) == "ARCTIS"


def test_apply_choice_device_sets_sink_and_source():
    sinks = FakeSinkManager()
    ok = daemon.apply_choice(sinks, "ARCTIS", CFG)
    assert ok is True
    assert ("sink", "Arctis Pro Wireless Analog Stereo") in sinks.calls
    assert ("source", "Arctis Pro Wireless Mono") in sinks.calls


def test_apply_choice_returns_false_when_sink_missing():
    sinks = FakeSinkManager(sink_ok=False)
    ok = daemon.apply_choice(sinks, "ARCTIS", CFG)
    assert ok is False


def test_apply_choice_fallback_system():
    sinks = FakeSinkManager()
    ok = daemon.apply_choice(sinks, None, CFG)
    assert ok is True
    assert ("auto",) in sinks.calls


def test_apply_choice_fallback_match():
    cfg = dict(CFG)
    cfg = {**CFG, "fallback": {"mode": "match", "substr": "USB Audio"}}
    sinks = FakeSinkManager()
    ok = daemon.apply_choice(sinks, None, cfg)
    assert ok is True
    assert ("match", "USB Audio") in sinks.calls


def test_apply_choice_fallback_unknown_mode():
    cfg = {**CFG, "fallback": {"mode": "bogus"}}
    sinks = FakeSinkManager()
    ok = daemon.apply_choice(sinks, None, cfg)
    assert ok is False
    assert sinks.calls == []


def test_apply_choice_fallback_disabled_leaves_sink_untouched():
    sinks = FakeSinkManager()
    ok = daemon.apply_choice(sinks, None, CFG, fallback_enabled=False)
    assert ok is True
    assert sinks.calls == []


def test_apply_choice_fallback_disabled_does_not_affect_real_device_choice():
    sinks = FakeSinkManager()
    ok = daemon.apply_choice(sinks, "ARCTIS", CFG, fallback_enabled=False)
    assert ok is True
    assert ("sink", "Arctis Pro Wireless Analog Stereo") in sinks.calls


def test_build_status_includes_battery_when_monitor_supports_it():
    monitors = {
        "WF1000XM5": FakeMonitor(False),
        "CETRA": FakeMonitorWithBattery(True, battery={"left": 100, "right": 100, "case": 71}),
        "ARCTIS": FakeMonitorWithBattery(False, battery=None),
    }
    status = daemon.build_status(monitors, "CETRA")
    assert status["active"] == "CETRA"
    assert status["devices"]["CETRA"] == {
        "connected": True,
        "battery": {"left": 100, "right": 100, "case": 71},
    }
    assert status["devices"]["ARCTIS"] == {"connected": False, "battery": None}
    # Monitor with no get_battery() at all (e.g. XM5Monitor) reports battery: None
    assert status["devices"]["WF1000XM5"] == {"connected": False, "battery": None}


def test_build_status_active_none_when_nothing_ready():
    monitors = {"CETRA": FakeMonitorWithBattery(False, battery=None)}
    status = daemon.build_status(monitors, None)
    assert status["active"] is None


def test_build_status_fallback_enabled_defaults_true():
    status = daemon.build_status({}, None)
    assert status["fallback_enabled"] is True


def test_build_status_reports_fallback_disabled():
    status = daemon.build_status({}, None, fallback_enabled=False)
    assert status["fallback_enabled"] is False


def test_read_settings_defaults_when_missing(tmp_path):
    path = tmp_path / "does-not-exist.json"
    assert daemon.read_settings(path=str(path)) == {"fallback_enabled": True}


def test_read_settings_reads_disabled_value(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"fallback_enabled": False}))
    assert daemon.read_settings(path=str(path)) == {"fallback_enabled": False}


def test_read_settings_defaults_on_malformed_json(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("not json")
    assert daemon.read_settings(path=str(path)) == {"fallback_enabled": True}


def test_write_status_file_writes_valid_json(tmp_path):
    path = tmp_path / "headset-status.json"
    status = {"active": "CETRA", "devices": {}, "updated": "2026-08-30T19:00:00"}
    daemon.write_status_file(status, path=str(path))
    with open(path) as f:
        loaded = json.load(f)
    assert loaded == status


def test_write_status_file_overwrites_atomically(tmp_path):
    path = tmp_path / "headset-status.json"
    daemon.write_status_file({"active": "A"}, path=str(path))
    daemon.write_status_file({"active": "B"}, path=str(path))
    with open(path) as f:
        loaded = json.load(f)
    assert loaded == {"active": "B"}
    assert not (tmp_path / "headset-status.json.tmp").exists()
