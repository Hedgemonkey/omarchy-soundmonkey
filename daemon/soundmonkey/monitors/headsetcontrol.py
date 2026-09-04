import subprocess
import json
import time
import threading
import logging

from .base import DeviceMonitor


# headsetcontrol's battery query can be flaky on some base stations: it fails
# with status "partial" both when the headset is genuinely on (base station
# reached it fine, only battery telemetry glitched: error message like "HID
# communication error") and when the headset is truly off (base station
# can't reach it at all: error message like "Device is offline or not
# responding"). Treating all "partial" as connected would mean a powered-off
# headset never gets detected as off; treating all "partial" as disconnected
# (the more common assumption) produces false negatives for a headset whose
# battery telemetry is merely flaky while it's genuinely in use. Distinguish
# on the specific battery error text instead - confirmed against a real
# SteelSeries Arctis Pro Wireless base station, but the same headsetcontrol
# status/error-string convention applies to any device it supports.
_OFFLINE_ERROR_MARKERS = ("offline", "not responding", "timed out")


def _is_connected(device):
    status = device.get("status")
    if status == "success":
        return True
    if status != "partial":
        return False

    battery_error = (device.get("errors", {}) or {}).get("battery", "") or ""
    battery_error = battery_error.lower()
    return not any(marker in battery_error for marker in _OFFLINE_ERROR_MARKERS)


class HeadsetControlMonitor(threading.Thread, DeviceMonitor):
    """Monitors any device supported by the `headsetcontrol` CLI.

    headsetcontrol (https://github.com/Sapd/HeadsetControl) supports dozens
    of headsets across SteelSeries, Corsair, Logitech, Razer, HyperX, and
    more - so this one class covers any of them via a config entry, with no
    new code required. `description_match` is matched against headsetcontrol's
    own device name field, which does not always match the PipeWire sink's
    description verbatim (hence the separate `sink_match` in config.yml).
    """

    def __init__(self, description_match, poll_interval_s=2.0, timeout_s=10.0):
        threading.Thread.__init__(self, daemon=True)
        self.description_match = description_match
        self.poll_interval_s = poll_interval_s
        self.timeout_s = timeout_s
        self._connected = False
        self._battery = None
        self._lock = threading.Lock()
        self._stop_event = threading.Event()

    def check_once(self):
        """Run a single headsetcontrol poll and update internal state.

        Public so tests can trigger a check synchronously without spinning
        up the polling thread.
        """
        try:
            out = subprocess.check_output(
                ["headsetcontrol", "--output", "json"],
                stderr=subprocess.DEVNULL,
                timeout=self.timeout_s,
            )
            data = json.loads(out)

            device = None
            for d in data.get("devices", []):
                if self.description_match in (d.get("device", "") or ""):
                    device = d
                    break

            if device and _is_connected(device):
                battery = None
                batt = device.get("battery")
                if isinstance(batt, dict):
                    battery = batt.get("level")
                with self._lock:
                    self._connected = True
                    self._battery = battery
            else:
                with self._lock:
                    self._connected = False
                    self._battery = None
        except subprocess.TimeoutExpired:
            logging.warning(f"{self.description_match}: headsetcontrol timeout")
            with self._lock:
                self._connected = False
                self._battery = None
        except Exception as e:
            logging.warning(f"{self.description_match}: headsetcontrol error: {e}")
            with self._lock:
                self._connected = False
                self._battery = None

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
