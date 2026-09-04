import json

from soundmonkey import settings

PLUGIN_ID = "hedgemonkey.soundmonkey"

CFG = {
    "devices": {
        "WF1000XM5": {"sink_match": "WF-1000XM5"},
        "CETRA": {"sink_match": "ROG CETRA"},
        "ARCTIS": {"sink_match": "Arctis Pro Wireless"},
    },
    "priority_order": ["WF1000XM5", "CETRA", "ARCTIS"],
}


def _write_shell_json(tmp_path, data):
    path = tmp_path / "shell.json"
    path.write_text(json.dumps(data))
    return str(path)


def test_read_user_settings_missing_file_returns_empty(tmp_path):
    path = str(tmp_path / "does-not-exist.json")
    assert settings.read_user_settings(PLUGIN_ID, path=path) == {}


def test_read_user_settings_malformed_json_returns_empty(tmp_path):
    path = tmp_path / "shell.json"
    path.write_text("not json")
    assert settings.read_user_settings(PLUGIN_ID, path=str(path)) == {}


def test_read_user_settings_no_matching_entry_returns_empty(tmp_path):
    path = _write_shell_json(tmp_path, {"bar": {"layout": {"right": [
        {"id": "some.other.plugin", "settings": {"fallbackEnabled": False}},
    ]}}})
    assert settings.read_user_settings(PLUGIN_ID, path=path) == {}


def test_read_user_settings_entry_with_no_settings_key_returns_empty(tmp_path):
    path = _write_shell_json(tmp_path, {"bar": {"layout": {"right": [
        {"id": PLUGIN_ID},
    ]}}})
    assert settings.read_user_settings(PLUGIN_ID, path=path) == {}


def test_read_user_settings_finds_entry_in_right_section(tmp_path):
    path = _write_shell_json(tmp_path, {"bar": {"layout": {"right": [
        {"id": PLUGIN_ID, "settings": {"fallbackEnabled": False}},
    ]}}})
    assert settings.read_user_settings(PLUGIN_ID, path=path) == {"fallbackEnabled": False}


def test_read_user_settings_finds_entry_in_left_section(tmp_path):
    path = _write_shell_json(tmp_path, {"bar": {"layout": {"left": [
        {"id": PLUGIN_ID, "settings": {"fallbackEnabled": False}},
    ]}}})
    assert settings.read_user_settings(PLUGIN_ID, path=path) == {"fallbackEnabled": False}


def test_read_user_settings_finds_entry_in_center_section(tmp_path):
    path = _write_shell_json(tmp_path, {"bar": {"layout": {"center": [
        {"id": PLUGIN_ID, "settings": {"fallbackEnabled": False}},
    ]}}})
    assert settings.read_user_settings(PLUGIN_ID, path=path) == {"fallbackEnabled": False}


def test_read_user_settings_falls_back_to_plugins_list(tmp_path):
    # A plugin that isn't a placed bar widget lives under top-level plugins[]
    # instead of bar.layout.<section>[].
    path = _write_shell_json(tmp_path, {"plugins": [
        {"id": PLUGIN_ID, "settings": {"fallbackEnabled": False}},
    ]})
    assert settings.read_user_settings(PLUGIN_ID, path=path) == {"fallbackEnabled": False}


def test_read_user_settings_non_dict_settings_value_returns_empty(tmp_path):
    path = _write_shell_json(tmp_path, {"bar": {"layout": {"right": [
        {"id": PLUGIN_ID, "settings": "not-a-dict"},
    ]}}})
    assert settings.read_user_settings(PLUGIN_ID, path=path) == {}


def test_resolve_settings_defaults_when_no_shell_json(tmp_path):
    path = str(tmp_path / "does-not-exist.json")
    resolved = settings.resolve_settings(PLUGIN_ID, CFG, path=path)
    assert resolved == {
        "priorityOrder": ["WF1000XM5", "CETRA", "ARCTIS"],
        "enabledDevices": {"WF1000XM5": True, "CETRA": True, "ARCTIS": True},
        "fallbackEnabled": True,
    }


def test_resolve_settings_priority_order_defaults_to_device_declaration_order():
    cfg = {"devices": {"A": {}, "B": {}, "C": {}}}  # no explicit priority_order
    resolved = settings.resolve_settings(PLUGIN_ID, cfg, path="/nonexistent")
    assert resolved["priorityOrder"] == ["A", "B", "C"]


def test_resolve_settings_user_priority_order_overrides_config(tmp_path):
    path = _write_shell_json(tmp_path, {"bar": {"layout": {"right": [
        {"id": PLUGIN_ID, "settings": {"priorityOrder": ["ARCTIS", "WF1000XM5", "CETRA"]}},
    ]}}})
    resolved = settings.resolve_settings(PLUGIN_ID, CFG, path=path)
    assert resolved["priorityOrder"] == ["ARCTIS", "WF1000XM5", "CETRA"]
    # Untouched keys still fall back to config-derived defaults.
    assert resolved["fallbackEnabled"] is True
    assert resolved["enabledDevices"] == {"WF1000XM5": True, "CETRA": True, "ARCTIS": True}


def test_resolve_settings_user_enabled_devices_overrides_config(tmp_path):
    path = _write_shell_json(tmp_path, {"bar": {"layout": {"right": [
        {"id": PLUGIN_ID, "settings": {"enabledDevices": {"WF1000XM5": False}}},
    ]}}})
    resolved = settings.resolve_settings(PLUGIN_ID, CFG, path=path)
    assert resolved["enabledDevices"] == {"WF1000XM5": False}


def test_resolve_settings_user_fallback_toggle_overrides_config(tmp_path):
    path = _write_shell_json(tmp_path, {"bar": {"layout": {"right": [
        {"id": PLUGIN_ID, "settings": {"fallbackEnabled": False}},
    ]}}})
    resolved = settings.resolve_settings(PLUGIN_ID, CFG, path=path)
    assert resolved["fallbackEnabled"] is False


def test_resolve_settings_only_matches_this_plugins_id(tmp_path):
    path = _write_shell_json(tmp_path, {"bar": {"layout": {"right": [
        {"id": "someone.else.plugin", "settings": {"fallbackEnabled": False}},
    ]}}})
    resolved = settings.resolve_settings(PLUGIN_ID, CFG, path=path)
    assert resolved["fallbackEnabled"] is True
