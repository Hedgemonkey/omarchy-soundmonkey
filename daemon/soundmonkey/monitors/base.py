from abc import ABC, abstractmethod


class DeviceMonitor(ABC):
    """Common interface every device monitor implements.

    daemon.py only ever talks to this interface - it never needs to know
    which detection mechanism (PipeWire presence, headsetcontrol, raw HID)
    a given device uses. Concrete monitors also subclass threading.Thread
    for start()/run(), which this ABC deliberately doesn't redeclare.
    """

    @abstractmethod
    def stop(self):
        """Signal the monitor's background thread to stop."""

    @abstractmethod
    def is_audio_ready(self) -> bool:
        """Whether the device is currently ready to receive audio."""

    def get_battery(self):
        """Battery reading (shape varies by device), or None if unavailable
        or unsupported. Default: unsupported."""
        return None
