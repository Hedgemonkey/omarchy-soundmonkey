import json
import subprocess

import pytest

from conftest import make_pw_node
from soundmonkey.sink_manager import SinkManager


def _patch_pw_dump(monkeypatch, nodes):
    """Make subprocess.check_output return the given pw-dump nodes as JSON."""
    payload = json.dumps(nodes).encode()

    def fake_check_output(cmd, **kwargs):
        assert cmd[0] == "pw-dump"
        return payload

    monkeypatch.setattr(subprocess, "check_output", fake_check_output)


def _patch_wpctl(monkeypatch):
    """Record wpctl set-default calls instead of running them."""
    calls = []

    def fake_run(cmd, **kwargs):
        assert cmd[0] == "wpctl"
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    return calls


def test_get_sinks_filters_by_media_class(monkeypatch):
    _patch_pw_dump(monkeypatch, [
        make_pw_node(99, "Audio/Sink", "ROG CETRA TRUE WIRELESS SPEEDNOVA Analog Stereo"),
        make_pw_node(100, "Audio/Source", "ROG CETRA TRUE WIRELESS SPEEDNOVA Mono"),
        make_pw_node(101, "Audio/Sink", "Arctis Pro Wireless Analog Stereo"),
    ])
    sinks = SinkManager()._get_sinks()
    assert sinks == {
        "ROG CETRA TRUE WIRELESS SPEEDNOVA Analog Stereo": 99,
        "Arctis Pro Wireless Analog Stereo": 101,
    }


def test_get_sources_filters_by_media_class(monkeypatch):
    _patch_pw_dump(monkeypatch, [
        make_pw_node(100, "Audio/Source", "ROG CETRA TRUE WIRELESS SPEEDNOVA Mono"),
    ])
    sources = SinkManager()._get_sources()
    assert sources == {"ROG CETRA TRUE WIRELESS SPEEDNOVA Mono": 100}


def test_set_default_by_description_substr(monkeypatch):
    _patch_pw_dump(monkeypatch, [
        make_pw_node(101, "Audio/Sink", "Arctis Pro Wireless Analog Stereo"),
    ])
    calls = _patch_wpctl(monkeypatch)
    ok = SinkManager().set_default_by_description_substr("Arctis Pro Wireless")
    assert ok is True
    assert calls == [["wpctl", "set-default", "101"]]


def test_set_default_by_description_substr_not_found(monkeypatch):
    _patch_pw_dump(monkeypatch, [make_pw_node(1, "Audio/Sink", "Other")])
    _patch_wpctl(monkeypatch)
    ok = SinkManager().set_default_by_description_substr("Arctis Pro Wireless")
    assert ok is False


def test_set_default_source_by_description_substr(monkeypatch):
    _patch_pw_dump(monkeypatch, [
        make_pw_node(102, "Audio/Source", "Arctis Pro Wireless Mono"),
    ])
    calls = _patch_wpctl(monkeypatch)
    ok = SinkManager().set_default_source_by_description_substr("Arctis Pro Wireless Mono")
    assert ok is True
    assert calls == [["wpctl", "set-default", "102"]]


_TEST_HEADSET_SUBSTRINGS = ["Arctis", "ROG CETRA", "WF-1000XM5"]


def test_set_internal_auto_skips_headsets(monkeypatch):
    _patch_pw_dump(monkeypatch, [
        make_pw_node(90, "Audio/Sink", "USB Audio Analog Stereo"),
        make_pw_node(101, "Audio/Sink", "Arctis Pro Wireless Analog Stereo"),
        make_pw_node(99, "Audio/Sink", "ROG CETRA TRUE WIRELESS SPEEDNOVA Analog Stereo"),
        make_pw_node(98, "Audio/Sink", "GB203 High Definition Audio Controller Digital Stereo (HDMI)"),
    ])
    calls = _patch_wpctl(monkeypatch)
    ok = SinkManager(headset_sink_substrings=_TEST_HEADSET_SUBSTRINGS).set_internal_auto()
    assert ok is True
    # Should pick the non-HDMI analog stereo sink, not a headset.
    assert calls == [["wpctl", "set-default", "90"]]


def test_set_internal_auto_only_headsets_returns_false(monkeypatch):
    _patch_pw_dump(monkeypatch, [
        make_pw_node(101, "Audio/Sink", "Arctis Pro Wireless Analog Stereo"),
    ])
    calls = _patch_wpctl(monkeypatch)
    ok = SinkManager(headset_sink_substrings=_TEST_HEADSET_SUBSTRINGS).set_internal_auto()
    assert ok is False
    assert calls == []


def test_set_internal_auto_headset_list_is_config_driven(monkeypatch):
    # Not hardcoded: a sink name unrelated to any of the "big three" is
    # correctly skipped as a headset purely because it's in the substring
    # list passed in - and conversely treated as a normal output when it's
    # not, with no code change either way.
    _patch_pw_dump(monkeypatch, [
        make_pw_node(90, "Audio/Sink", "USB Audio Analog Stereo"),
        make_pw_node(77, "Audio/Sink", "Corsair Void Pro Wireless Analog Stereo"),
    ])
    calls = _patch_wpctl(monkeypatch)
    ok = SinkManager(headset_sink_substrings=["Corsair Void"]).set_internal_auto()
    assert ok is True
    assert calls == [["wpctl", "set-default", "90"]]


def test_set_internal_auto_with_no_headset_substrings_treats_everything_as_internal(monkeypatch):
    _patch_pw_dump(monkeypatch, [
        make_pw_node(101, "Audio/Sink", "Arctis Pro Wireless Analog Stereo"),
    ])
    calls = _patch_wpctl(monkeypatch)
    ok = SinkManager().set_internal_auto()
    assert ok is True
    assert calls == [["wpctl", "set-default", "101"]]


def test_set_internal_match(monkeypatch):
    _patch_pw_dump(monkeypatch, [
        make_pw_node(90, "Audio/Sink", "USB Audio Analog Stereo"),
    ])
    calls = _patch_wpctl(monkeypatch)
    ok = SinkManager().set_internal_match("USB Audio")
    assert ok is True
    assert calls == [["wpctl", "set-default", "90"]]


def test_set_internal_match_not_found(monkeypatch):
    _patch_pw_dump(monkeypatch, [make_pw_node(1, "Audio/Sink", "Other")])
    _patch_wpctl(monkeypatch)
    ok = SinkManager().set_internal_match("USB Audio")
    assert ok is False


def test_get_nodes_passes_timeout(monkeypatch):
    """Ensure _get_nodes forwards a timeout so it cannot hang forever."""
    captured = {}

    def fake_check_output(cmd, **kwargs):
        captured["kwargs"] = kwargs
        return json.dumps([make_pw_node(1, "Audio/Sink", "x")]).encode()

    monkeypatch.setattr(subprocess, "check_output", fake_check_output)
    SinkManager()._get_sinks()
    assert captured["kwargs"].get("timeout") == 5.0
