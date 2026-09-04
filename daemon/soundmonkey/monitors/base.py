from abc import ABC, abstractmethod


class DeviceMonitor(ABC):
    """Common interface every device monitor implements.

    daemon.py only ever talks to this interface - it never needs to know
    which detection mechanism (PipeWire presence, headsetcontrol, raw HID) a
    given device uses, or how many background threads (zero, one, or several
    composed sub-monitors) it takes to implement one. Most concrete monitors
    subclass threading.Thread and get start() for free; a composite monitor
    that owns other monitors instead of polling anything itself (see
    CetraHidMonitor) implements start()/stop() directly to fan out to its
    children.
    """

    @abstractmethod
    def start(self):
        """Begin monitoring (idempotent-per-instance, not expected to be
        called twice)."""

    @abstractmethod
    def stop(self):
        """Stop monitoring - the background thread(s) this owns, and any
        composed sub-monitors."""

    @abstractmethod
    def is_audio_ready(self) -> bool:
        """Whether the device is currently ready to receive audio."""

    def get_battery(self):
        """Battery reading (shape varies by device), or None if unavailable
        or unsupported. Default: unsupported."""
        return None
