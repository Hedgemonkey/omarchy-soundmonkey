import subprocess
import json
import threading
import time
import logging

try:
    import hid
except ImportError:  # pragma: no cover
    hid = None


class CetraMonitor(threading.Thread):
    """Monitors the ROG CETRA TRUE WIRELESS SPEEDNOVA dongle.

    Audio-routing readiness is detected the same way XM5Monitor does: by
    checking whether the Cetra sink exists in the PipeWire graph. The sink is
    present whenever the USB dongle is plugged in, which is the right signal
    for priority routing.

    Battery level is read separately from raw HID reports on the vendor page.
    Confirmed via a live capture (2026-08-30, marker-synced against physical
    actions): report ID 204 (0xcc) with subtype byte 0x09 carries left/right/
    case battery percentages at offsets 5-7. In-ear/out-of-ear wear state is
    NOT exposed on this endpoint - multiple clean in/out cycles produced zero
    HID traffic. ASUS's own wear-detection feature (togglable in Armoury
    Crate) has no dedicated optical sensor and appears to infer fit
    acoustically inside the earbud's own DSP, never surfacing as a queryable
    state.

    A genuine session on/off signal DOES exist, separate from wear detection:
    subtype 0x01 with state byte 0x00 (offset 5) fires once, right as the
    earbuds are taken out of the ears to be put away - confirmed via a
    marker-synced capture (2026-08-30) showing 36+ seconds of total silence
    through a full wear cycle, then this exact report the moment they were
    removed to be docked, followed by silence through case-close. The same
    subtype with a nonzero state byte (0x01/0x10/0x11 observed) is part of
    the connect handshake when they leave the case. Combined with the
    PipeWire sink check (which only reflects "dongle plugged in"), this lets
    is_audio_ready() distinguish "actually in a listening session" from
    "dongle present but earbuds docked" - the gap that let Cetra wrongly keep
    audio priority after being put away.
    """

    VID = 0x0b05
    PID = 0x1ad3

    def __init__(self, description_match="ROG CETRA TRUE WIRELESS SPEEDNOVA",
                 timeout_ms=5000):
        super().__init__(daemon=True)
        # timeout_ms retained for API compatibility but not used for HID anymore
        self.timeout_ms = timeout_ms
        self.description_match = description_match
        self._connected = False
        self._battery = None
        # Optimistic default: if the daemon starts (or restarts) while the
        # earbuds are already out and in use, there's no fresh connect event
        # to observe, so assume a session is active until an explicit
        # power-off report (subtype 0x01, state byte 0x00) says otherwise.
        self._session_active = True
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._hid_thread = threading.Thread(target=self._hid_loop, daemon=True)

    def _check_pw(self):
        try:
            out = subprocess.check_output(
                ["pw-dump"],
                stderr=subprocess.DEVNULL,
                timeout=5.0,
            )
            nodes = json.loads(out)
            found = False
            for obj in nodes:
                props = obj.get("info", {}).get("props", {})
                if props.get("media.class") == "Audio/Sink" and \
                   self.description_match in (props.get("node.description", "") or ""):
                    found = True
                    break
            with self._lock:
                self._connected = found
            return found
        except subprocess.TimeoutExpired:
            logging.warning("Cetra: pw-dump timeout")
            with self._lock:
                self._connected = False
            return False
        except Exception as e:
            logging.warning(f"Cetra: pw-dump error: {e}")
            with self._lock:
                self._connected = False
            return False

    def _process_report(self, data):
        """Update state from one raw HID report. Returns True if it was a
        recognised report (battery or session state)."""
        if len(data) >= 8 and data[0] == 0xcc and data[1] == 0x12:
            subtype = data[2]
            if subtype == 0x09:
                battery = {"left": data[5], "right": data[6], "case": data[7]}
                with self._lock:
                    self._battery = battery
                return True
            if subtype == 0x01:
                with self._lock:
                    self._session_active = data[5] != 0x00
                return True
        return False

    def _hid_loop(self):
        if hid is None:
            logging.warning("Cetra: python 'hid' module not available, skipping battery reporting")
            return
        while not self._stop.is_set():
            try:
                devs = hid.enumerate(self.VID, self.PID)
                if not devs:
                    time.sleep(2.0)
                    continue
                dev = hid.Device(path=devs[0]["path"])
                try:
                    while not self._stop.is_set():
                        data = dev.read(64, timeout=2000)
                        if data:
                            self._process_report(data)
                finally:
                    dev.close()
            except Exception as e:
                logging.warning(f"Cetra: hid read error: {e}")
                time.sleep(2.0)

    def run(self):
        self._hid_thread.start()
        while not self._stop.is_set():
            connected = self._check_pw()
            with self._lock:
                self._connected = connected
            time.sleep(2.0)

    def stop(self):
        self._stop.set()

    def is_audio_ready(self):
        with self._lock:
            return self._connected and self._session_active

    def get_battery(self):
        with self._lock:
            return dict(self._battery) if self._battery else None
