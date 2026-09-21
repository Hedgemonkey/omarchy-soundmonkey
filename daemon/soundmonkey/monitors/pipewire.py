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

    Bluetooth battery reporting needs no config at all: a Bluetooth sink's
    PipeWire node already carries its own MAC in the `api.bluez5.address`
    prop (confirmed via `pw-dump` against the WF-1000XM5 - every profile of
    a bluez5 sink node has it), so once a poll matches the sink, that address
    is reused to ask BlueZ (via `bluetoothctl info`) for battery percentage,
    for any Bluetooth device that reports one - no vendor-specific protocol
    work, no MAC to look up and paste into config.yml by hand. `mac_address`
    is an optional escape hatch (a device whose matched node somehow lacks
    the prop, or polling a different node's address than the one that
    matches `description_match`) - most devices never need it. A USB device,
    or a Bluetooth device with no battery reporting, just never gets a
    detected address, and `get_battery()` stays unsupported (returns None),
    same as before this was added.
    """

    def __init__(self, description_match, poll_interval_s=2.0, mac_address=None):
        threading.Thread.__init__(self, daemon=True)
        self.description_match = description_match
        self.poll_interval_s = poll_interval_s
        self.mac_address = mac_address
        self._connected = False
        self._battery = None
        self._detected_mac_address = None
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
            matched_props = self._matches(nodes)
        except subprocess.TimeoutExpired:
            logging.warning(f"{self.description_match}: pw-dump timeout")
            matched_props = None
        except Exception as e:
            logging.warning(f"{self.description_match}: pw-dump error: {e}")
            matched_props = None

        found = matched_props is not None
        if found:
            detected = matched_props.get("api.bluez5.address")
            if detected:
                self._detected_mac_address = detected

        with self._lock:
            self._connected = found

        # Persist the detected address across polls (it never changes for a
        # given physical device) so a momentary sink disappearance doesn't
        # also blank out the battery reading.
        mac_address = self.mac_address or self._detected_mac_address
        if mac_address:
            self._check_battery(mac_address)

        return found

    def _check_battery(self, mac_address):
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
                ["bluetoothctl", "info", mac_address],
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
        """Return the matching sink node's props dict, or None."""
        for obj in nodes:
            props = obj.get("info", {}).get("props", {})
            if props.get("media.class") == "Audio/Sink" and \
               self.description_match in (props.get("node.description", "") or ""):
                return props
        return None

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
