import threading
import time
import logging

try:
    import hid
except ImportError:  # pragma: no cover
    hid = None

from .base import DeviceMonitor
from .pipewire import PipewirePresenceMonitor


class CetraHidMonitor(DeviceMonitor):
    """Monitors the ASUS ROG Cetra True Wireless SPEEDNOVA dongle.

    Audio-routing readiness composes two independent signals: a
    PipewirePresenceMonitor for "is the USB dongle plugged in" (delegated to
    rather than reimplemented - the sink-presence check is identical to any
    other PipeWire-visible device), and this class's own raw-HID listener
    for the earbuds' session on/off state, since the dongle's sink stays
    present the whole time it's plugged in regardless of whether the
    earbuds themselves are being worn or sitting docked.

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
    PipeWire sink check, this lets is_audio_ready() distinguish "actually in
    a listening session" from "dongle present but earbuds docked" - the gap
    that would otherwise let Cetra wrongly keep audio priority after being
    put away.

    This class is intentionally not itself a threading.Thread: it has no
    polling loop of its own to run, only two owned components (the composed
    PipewirePresenceMonitor, and its own HID listener thread) to start and
    stop together.
    """

    VID = 0x0b05
    PID = 0x1ad3

    def __init__(self, description_match="ROG CETRA TRUE WIRELESS SPEEDNOVA"):
        self.description_match = description_match
        self._pw_monitor = PipewirePresenceMonitor(description_match=description_match)
        self._battery = None
        # Default to inactive until an explicit connect report (subtype
        # 0x01, nonzero state byte) is observed. Previously defaulted to
        # active to cover a daemon (re)start while the earbuds were already
        # out - but that meant a device that, for whatever reason, never
        # gets detected properly would sit there falsely reporting "ready"
        # instead of visibly needing attention. Detection has proven
        # reliable enough that this false-positive risk isn't worth it
        # anymore; the fix for a genuine miss is a normal case-out/case-in
        # cycle, which reliably fires this same connect report.
        self._session_active = False
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._hid_thread = threading.Thread(target=self._hid_loop, daemon=True)

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
        while not self._stop_event.is_set():
            try:
                devs = hid.enumerate(self.VID, self.PID)
                if not devs:
                    time.sleep(2.0)
                    continue
                dev = hid.Device(path=devs[0]["path"])
                try:
                    while not self._stop_event.is_set():
                        data = dev.read(64, timeout=2000)
                        if data:
                            self._process_report(data)
                finally:
                    dev.close()
            except Exception as e:
                logging.warning(f"Cetra: hid read error: {e}")
                time.sleep(2.0)

    def start(self):
        self._pw_monitor.start()
        self._hid_thread.start()

    def stop(self):
        self._pw_monitor.stop()
        self._stop_event.set()

    def is_audio_ready(self):
        with self._lock:
            session_active = self._session_active
        return self._pw_monitor.is_audio_ready() and session_active

    def get_battery(self):
        with self._lock:
            return dict(self._battery) if self._battery else None
