from .base import DeviceMonitor
from .pipewire import PipewirePresenceMonitor
from .headsetcontrol import HeadsetControlMonitor
from .cetra_hid import CetraHidMonitor

# Maps a config.yml device's `type:` string to the monitor class that
# implements it. daemon.py's build_monitors() looks devices up here instead
# of hardcoding a class per device name - adding a device that fits an
# existing type (e.g. any headsetcontrol-supported headset, or anything that
# just needs "does a matching sink exist") is a config-only change. A
# genuinely new protocol needs one new DeviceMonitor subclass and one entry
# here; nothing else in the daemon changes.
MONITOR_TYPES = {
    "pipewire-presence": PipewirePresenceMonitor,
    "headsetcontrol": HeadsetControlMonitor,
    "cetra-hid": CetraHidMonitor,
}

__all__ = [
    "DeviceMonitor",
    "MONITOR_TYPES",
    "PipewirePresenceMonitor",
    "HeadsetControlMonitor",
    "CetraHidMonitor",
]
