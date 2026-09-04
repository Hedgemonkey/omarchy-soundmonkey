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
        "WF1000XM5": {
            "type": "pipewire-presence",
            "sink_match": "WF-1000XM5", "source_match": "bluez_input",
            "monitor": {"description_match": "WF-1000XM5"},
        },
        "CETRA": {
            "type": "cetra-hid",
            "sink_match": "ROG CETRA", "source_match": "ROG CETRA Mono",
            "monitor": {"description_match": "ROG CETRA TRUE WIRELESS SPEEDNOVA"},
        },
        "ARCTIS": {
            "type": "headsetcontrol",
            "sink_match": "Arctis Pro Wireless Analog Stereo",
            "source_match": "Arctis Pro Wireless Mono",
            "monitor": {"description_match": "Arctis Pro Wireless"},
        },
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


def test_build_monitors_adds_a_new_device_via_config_only():
    # The whole point of the registry: a device using an *existing* monitor
    # type needs no daemon.py change, just a config entry - proves the OCP
    # fix actually works, not just that the old three still build.
    cfg = {"devices": {**CFG["devices"], "COUCH_SPEAKER": {
        "type": "pipewire-presence",
        "sink_match": "Couch Bluetooth Speaker",
        "monitor": {"description_match": "Couch Bluetooth Speaker"},
    }}}
    monitors = daemon.build_monitors(cfg)
    from soundmonkey.monitors.pipewire import PipewirePresenceMonitor
    assert "COUCH_SPEAKER" in monitors
    assert isinstance(monitors["COUCH_SPEAKER"], PipewirePresenceMonitor)


def test_build_monitors_skips_unknown_type():
    cfg = {"devices": {"MYSTERY": {"type": "not-a-real-type", "monitor": {}}}}
    monitors = daemon.build_monitors(cfg)
    assert monitors == {}


def test_build_monitors_skips_invalid_monitor_kwargs():
    # pipewire-presence requires description_match; omitting it is a
    # TypeError at construction time, which should be caught and skipped
    # rather than crashing the whole daemon over one bad device entry.
    cfg = {"devices": {"BROKEN": {"type": "pipewire-presence", "monitor": {}}}}
    monitors = daemon.build_monitors(cfg)
    assert monitors == {}


def test_build_monitors_one_bad_device_does_not_block_the_others():
    cfg = {"devices": {
        **CFG["devices"],
        "BROKEN": {"type": "not-a-real-type", "monitor": {}},
    }}
    monitors = daemon.build_monitors(cfg)
    assert set(monitors.keys()) == {"WF1000XM5", "CETRA", "ARCTIS"}


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


def test_decide_choice_skips_disabled_device_even_if_ready():
    monitors = {
        "WF1000XM5": FakeMonitor(True),
        "CETRA": FakeMonitor(True),
    }
    enabled = {"WF1000XM5": False, "CETRA": True}
    assert daemon.decide_choice(monitors, ["WF1000XM5", "CETRA"], enabled) == "CETRA"


def test_decide_choice_device_missing_from_enabled_map_defaults_enabled():
    # A device added to config.yml but never touched in the panel yet
    # should still work, not be silently excluded.
    monitors = {"WF1000XM5": FakeMonitor(True)}
    assert daemon.decide_choice(monitors, ["WF1000XM5"], enabled_devices={}) == "WF1000XM5"


def test_decide_choice_all_disabled_returns_none():
    monitors = {"WF1000XM5": FakeMonitor(True)}
    enabled = {"WF1000XM5": False}
    assert daemon.decide_choice(monitors, ["WF1000XM5"], enabled) is None


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
    status = daemon.build_status(monitors, "CETRA", cfg=CFG)
    assert status["active"] == "CETRA"
    assert status["devices"]["CETRA"] == {
        "connected": True,
        "battery": {"left": 100, "right": 100, "case": 71},
        "label": "CETRA",
    }
    assert status["devices"]["ARCTIS"] == {"connected": False, "battery": None, "label": "ARCTIS"}
    # Monitor with no get_battery() at all (e.g. PipewirePresenceMonitor)
    # reports battery: None
    assert status["devices"]["WF1000XM5"] == {"connected": False, "battery": None, "label": "WF1000XM5"}


def test_build_status_uses_configured_display_name_as_label():
    monitors = {"CETRA": FakeMonitorWithBattery(True, battery=None)}
    cfg = {"devices": {"CETRA": {"name": "ROG Cetra"}}}
    status = daemon.build_status(monitors, "CETRA", cfg=cfg)
    assert status["devices"]["CETRA"]["label"] == "ROG Cetra"


def test_build_status_label_defaults_to_device_key_without_cfg():
    monitors = {"CETRA": FakeMonitorWithBattery(True, battery=None)}
    status = daemon.build_status(monitors, "CETRA")
    assert status["devices"]["CETRA"]["label"] == "CETRA"


def test_build_status_includes_priority_order():
    monitors = {"CETRA": FakeMonitor(True), "ARCTIS": FakeMonitor(False)}
    status = daemon.build_status(monitors, "CETRA", priority_order=["ARCTIS", "CETRA"])
    assert status["priority_order"] == ["ARCTIS", "CETRA"]


def test_build_status_priority_order_defaults_to_monitor_keys_without_one():
    monitors = {"CETRA": FakeMonitor(True)}
    status = daemon.build_status(monitors, "CETRA")
    assert status["priority_order"] == ["CETRA"]


def test_build_status_includes_enabled_devices():
    monitors = {"CETRA": FakeMonitor(True)}
    status = daemon.build_status(monitors, "CETRA", enabled_devices={"CETRA": False})
    assert status["enabled_devices"] == {"CETRA": False}


def test_build_status_enabled_devices_defaults_to_empty_dict():
    monitors = {"CETRA": FakeMonitor(True)}
    status = daemon.build_status(monitors, "CETRA")
    assert status["enabled_devices"] == {}


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
