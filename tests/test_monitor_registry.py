from soundmonkey.monitors import DeviceMonitor, MONITOR_TYPES
from soundmonkey.monitors.pipewire import PipewirePresenceMonitor
from soundmonkey.monitors.headsetcontrol import HeadsetControlMonitor
from soundmonkey.monitors.cetra_hid import CetraHidMonitor


def test_pipewire_presence_registered():
    assert MONITOR_TYPES["pipewire-presence"] is PipewirePresenceMonitor


def test_headsetcontrol_registered():
    assert MONITOR_TYPES["headsetcontrol"] is HeadsetControlMonitor


def test_cetra_hid_registered():
    assert MONITOR_TYPES["cetra-hid"] is CetraHidMonitor


def test_registered_types_implement_device_monitor():
    for monitor_cls in MONITOR_TYPES.values():
        assert issubclass(monitor_cls, DeviceMonitor)


def test_device_monitor_is_abstract():
    import pytest

    with pytest.raises(TypeError):
        DeviceMonitor()
