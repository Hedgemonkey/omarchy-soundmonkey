import subprocess
import json
import time
import threading
import logging


# headsetcontrol's battery query over this headset's base station is flaky:
# it fails with status "partial" both when the headset is genuinely on (base
# station reached it fine, only battery telemetry glitched: error message
# "HID communication error") and when the headset is truly off (base station
# can't reach it at all: error message "Device is offline or not responding").
# Treating all "partial" as connected (as a prior version of this code did)
# meant a powered-off headset never got detected as off. Distinguish on the
# specific battery error text instead: "offline"/"not responding" means off.
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


class ArctisState:
    def __init__(self):
        self.connected = False
        self.battery = None
        self.lock = threading.Lock()


class ArctisMonitor(threading.Thread):
    def __init__(self, description_match="Arctis Pro Wireless", timeout_s=10.0):
        super().__init__(daemon=True)
        self.description_match = description_match
        self.timeout_s = timeout_s
        self.state = ArctisState()
        self._stop = threading.Event()

    def _poll_once(self):
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
                with self.state.lock:
                    self.state.connected = True
                    self.state.battery = battery
            else:
                with self.state.lock:
                    self.state.connected = False
                    self.state.battery = None
        except subprocess.TimeoutExpired:
            logging.warning("Arctis: headsetcontrol timeout")
            with self.state.lock:
                self.state.connected = False
                self.state.battery = None
        except Exception as e:
            logging.warning(f"Arctis: headsetcontrol error: {e}")
            with self.state.lock:
                self.state.connected = False
                self.state.battery = None

    def run(self):
        while not self._stop.is_set():
            self._poll_once()
            time.sleep(2.0)

    def stop(self):
        self._stop.set()

    def is_audio_ready(self):
        with self.state.lock:
            return self.state.connected

    def get_battery(self):
        with self.state.lock:
            return self.state.battery
