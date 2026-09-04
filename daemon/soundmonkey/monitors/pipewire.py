import subprocess
import json
import threading
import time
import logging

from .base import DeviceMonitor


class PipewirePresenceMonitor(DeviceMonitor, threading.Thread):
    """Reports a device ready whenever a PipeWire sink whose description
    contains `description_match` exists in the audio graph.

    The right detection mechanism for any device that only shows up when
    actually active/plugged in and needs no richer telemetry than "is it
    there right now" - covers most simple Bluetooth/USB audio devices.
    Composable: other monitors (e.g. CetraHidMonitor) hold one of these as
    their own "is the dongle present" building block instead of duplicating
    the pw-dump polling loop.
    """

    def __init__(self, description_match, poll_interval_s=2.0):
        threading.Thread.__init__(self, daemon=True)
        self.description_match = description_match
        self.poll_interval_s = poll_interval_s
        self._connected = False
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
        return found

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
