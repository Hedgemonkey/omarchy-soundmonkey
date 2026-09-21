import re
import subprocess
import json
import threading
import time
import logging

from .base import DeviceMonitor

# BlueZ auto-creates org.bluez.Battery1 on a device's D-Bus object once it
# reports battery level over AVRCP or HFP - true for most Bluetooth
# headsets/earbuds, not just Sony's. `bluetoothctl info` surfaces it as a
# plain "Battery Percentage: 0x64 (100)" line, which is far simpler to poll
# than resolving the device's adapter-qualified D-Bus object path ourselves.
_BATTERY_LINE_RE = re.compile(r"Battery Percentage:.*\((\d+)\)")


class PipewirePresenceMonitor(threading.Thread, DeviceMonitor):
    """Reports a device ready whenever a PipeWire sink whose description
    contains `description_match` exists in the audio graph.

    The right detection mechanism for any device that only shows up when
    actually active/plugged in and needs no richer telemetry than "is it
    there right now" - covers most simple Bluetooth/USB audio devices.
    Composable: other monitors (e.g. CetraHidMonitor) hold one of these as
    their own "is the dongle present" building block instead of duplicating
    the pw-dump polling loop.

    `mac_address` is optional: when given, each poll also asks BlueZ (via
    `bluetoothctl info`) for the device's battery percentage, for any
    Bluetooth device that exposes one - no vendor-specific protocol work
    needed. Omit it for USB devices or Bluetooth devices with no battery
    reporting; `get_battery()` then stays unsupported (returns None), same
    as before this was added.
    """

    def __init__(self, description_match, poll_interval_s=2.0, mac_address=None):
        threading.Thread.__init__(self, daemon=True)
        self.description_match = description_match
        self.poll_interval_s = poll_interval_s
        self.mac_address = mac_address
        self._connected = False
        self._battery = None
        self._lock = threading.Lock()
        self._stop_event = threading.Event()

    def check_once(self):
        """Run a single pw-dump check and update internal state.

        Public so composing monitors and tests can trigger a check
        synchronously without spinning up the polling thread.
        """
        try:
            out = subprocess.check_output(
                ["pw-dump"],
                stderr=subprocess.DEVNULL,
                timeout=2.0,
            )
            nodes = json.loads(out)
            found = self._matches(nodes)
        except subprocess.TimeoutExpired:
            logging.warning(f"{self.description_match}: pw-dump timeout")
            found = False
        except Exception as e:
            logging.warning(f"{self.description_match}: pw-dump error: {e}")
            found = False

        with self._lock:
            self._connected = found

        if self.mac_address:
            self._check_battery()

        return found

    def _check_battery(self):
        """Poll BlueZ for the device's battery percentage, if it reports one.

        Independent of the pw-dump presence check above: a device can be
        paired/connected (and answer this) while not currently the default
        sink, and vice versa while a stale battery reading lingers briefly
        after disconnect. Failure here (bluetoothctl missing, device not
        connected, no Battery1 interface) is non-fatal - just leaves battery
        unknown, same as a device type that never supported it.
        """
        battery = None
        try:
            out = subprocess.check_output(
                ["bluetoothctl", "info", self.mac_address],
                stderr=subprocess.DEVNULL,
                timeout=2.0,
            ).decode(errors="replace")
            match = _BATTERY_LINE_RE.search(out)
            if match:
                battery = int(match.group(1))
        except subprocess.TimeoutExpired:
            logging.warning(f"{self.description_match}: bluetoothctl timeout")
        except Exception as e:
            logging.warning(f"{self.description_match}: bluetoothctl battery error: {e}")

        with self._lock:
            self._battery = battery

    def _matches(self, nodes):
        for obj in nodes:
            props = obj.get("info", {}).get("props", {})
            if props.get("media.class") == "Audio/Sink" and \
               self.description_match in (props.get("node.description", "") or ""):
                return True
        return False

    def run(self):
        while not self._stop_event.is_set():
            self.check_once()
            time.sleep(self.poll_interval_s)

    def stop(self):
        self._stop_event.set()

    def is_audio_ready(self):
        with self._lock:
            return self._connected

    def get_battery(self):
        with self._lock:
            return self._battery
