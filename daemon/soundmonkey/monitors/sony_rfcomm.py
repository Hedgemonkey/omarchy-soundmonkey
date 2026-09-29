import socket
import threading
import time
import logging

from .base import DeviceMonitor
from .pipewire import PipewirePresenceMonitor

# Sony's proprietary vendor serial service, present in every MDR-protocol
# device's own SDP record (confirmed on a WF-1000XM5 via `bluetoothctl info`)
# - not used directly here since the channel is passed in, but kept as a
# reference for anyone re-resolving it via `sdptool browse`.
SONY_SPP_UUID = "956c7b26-d49a-4ba8-b03f-b17d393cb6e2"

_START = 0x3e
_END = 0x3c
_ESCAPE = 0x3d
_ESCAPE_MASK = 0xEF
_UNESCAPE_MASK = 0x10
_DATA_MDR = 0x0c  # v1 command table - carries battery on every model confirmed so far
_ACK = 0x01


def _checksum(body):
    total = 0
    for b in body:
        total = (total + b) & 0xff
    return total


def _encode_frame(data_type, seq, payload):
    """`0x3e | dataType | seq | payloadLength(u32 BE) | payload | checksum | 0x3c`,
    with 0x3e/0x3c/0x3d in the body+checksum escaped as 0x3d followed by the
    byte with bit 4 cleared. Format confirmed against a live device by
    sonyctl (https://github.com/DaanHessen/sonyctl/blob/master/docs/protocol.md)."""
    body = bytearray([data_type, seq]) + len(payload).to_bytes(4, "big") + bytes(payload)
    body.append(_checksum(body))
    out = bytearray([_START])
    for b in body:
        if b in (_START, _END, _ESCAPE):
            out.append(_ESCAPE)
            out.append(b & _ESCAPE_MASK)
        else:
            out.append(b)
    out.append(_END)
    return bytes(out)


def _unescape(buf):
    out = bytearray()
    it = iter(buf)
    for b in it:
        if b == _ESCAPE:
            nxt = next(it, None)
            if nxt is None:
                raise ValueError("truncated escape sequence")
            out.append(nxt | _UNESCAPE_MASK)
        else:
            out.append(b)
    return bytes(out)


def _decode_frame(buf):
    """Pull one complete frame off the front of `buf` (mutated in place), or
    None if it doesn't hold a whole frame yet."""
    try:
        start = buf.index(_START)
    except ValueError:
        return None
    try:
        end_offset = buf.index(_END, start + 1)
    except ValueError:
        return None

    unescaped = _unescape(buf[start + 1:end_offset])
    del buf[:end_offset + 1]

    if len(unescaped) < 7:
        raise ValueError("frame too short")
    body, checksum_byte = unescaped[:-1], unescaped[-1]
    if _checksum(body) != checksum_byte:
        raise ValueError("checksum mismatch")

    declared_len = int.from_bytes(body[2:6], "big")
    payload = body[6:]
    if len(payload) != declared_len:
        raise ValueError("length mismatch")
    return body[0], body[1], payload


class _SonySession:
    """One request/response session over a freshly opened RFCOMM socket -
    opened, queried, and closed per poll rather than held open, so a device
    sleep or disconnect between polls just fails the next connection attempt
    instead of leaving a stuck socket to detect and recover."""

    def __init__(self, address, channel, timeout_s=3.0):
        self.sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
        self.sock.settimeout(timeout_s)
        self.sock.connect((address, channel))
        # The RFCOMM socket reports connected slightly before it can carry
        # data; writing immediately reliably returns ENOTCONN (confirmed
        # against this exact protocol by sonyctl's docs/protocol.md).
        time.sleep(0.4)
        self.tx_seq = 0
        self.buf = bytearray()

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass

    def _read_frame(self):
        while True:
            frame = _decode_frame(self.buf)
            if frame is not None:
                return frame
            chunk = self.sock.recv(512)
            if not chunk:
                raise ConnectionError("RFCOMM socket closed")
            self.buf.extend(chunk)

    def _write_frame(self, data_type, seq, payload):
        self.sock.sendall(_encode_frame(data_type, seq, payload))

    def _ack(self, received_seq):
        self._write_frame(_ACK, received_seq ^ 1, b"")

    def request(self, payload):
        """Send a command frame, wait for its ack, then return the next
        non-ack data frame's payload - acking anything else (notifications)
        along the way, mirroring sonyctl's send()+recv() pairing."""
        self._write_frame(_DATA_MDR, self.tx_seq, payload)
        while True:
            dt, seq, _pl = self._read_frame()
            if dt == _ACK:
                self.tx_seq ^= 1
                break
            self._ack(seq)

        while True:
            dt, seq, pl = self._read_frame()
            if dt == _ACK:
                continue
            self._ack(seq)
            return pl


def _query_battery(address, channel):
    """One-shot connect + battery query.

    Confirmed live against a WF-1000XM5 (2026-09-29, all `charging` bytes
    0x00 at the time): `22 01` returns left+right as two back-to-back
    (percent, charging) pairs (`23 01 <lp> <lc> <rp> <rc>`), and `22 02`
    returns the case as one pair (`23 02 <cp> <cc>`). `22 00` (the merged
    reading also exposed generically via BlueZ/AVRCP, which is what
    pipewire.py's get_battery() already returns) and `22 03` (which times
    out - there is no fourth battery slot) are not queried here.
    """
    session = _SonySession(address, channel)
    try:
        session.request(bytes([0x00, 0x00]))  # protocol-info handshake; other commands don't answer without it
        lr = session.request(bytes([0x22, 0x01]))
        case = session.request(bytes([0x22, 0x02]))
    finally:
        session.close()

    if len(lr) < 6 or len(case) < 4:
        raise ValueError(f"unexpected battery payload shape: lr={lr.hex()} case={case.hex()}")
    return {"left": lr[2], "right": lr[4], "case": case[2]}


class SonyRfcommMonitor(DeviceMonitor):
    """Left/right/case battery for Sony MDR v2 TWS earbuds (confirmed on a
    WF-1000XM5; likely the same across the MDR v2 line), read over the same
    proprietary RFCOMM channel Sony's own app uses - the single BlueZ/AVRCP
    percentage pipewire.py already exposes has no per-bud breakdown at all.
    This rides the existing classic Bluetooth (A2DP) bond; no LE pairing
    needed.

    Composes PipewirePresenceMonitor for is_audio_ready() rather than
    reimplementing presence detection - same rationale as CetraHidMonitor.
    This class contributes only the richer battery reading, and only polls
    it while the device is actually present, so a device that's off or out
    of range isn't hit with repeated RFCOMM connect attempts.
    """

    def __init__(self, description_match, mac_address, channel=9, poll_interval_s=30.0):
        self.mac_address = mac_address
        self.channel = channel
        self.poll_interval_s = poll_interval_s
        self._pw_monitor = PipewirePresenceMonitor(description_match=description_match)
        self._battery = None
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)

    def _poll_loop(self):
        while not self._stop_event.is_set():
            if self._pw_monitor.is_audio_ready():
                try:
                    battery = _query_battery(self.mac_address, self.channel)
                    with self._lock:
                        self._battery = battery
                except Exception as e:
                    logging.warning(f"Sony RFCOMM ({self.mac_address}): battery query failed: {e}")
                self._stop_event.wait(self.poll_interval_s)
            else:
                # Recheck readiness on PipewirePresenceMonitor's own cadence
                # rather than this monitor's much longer battery interval -
                # otherwise a device that becomes ready right after this
                # check waits up to poll_interval_s before its first reading.
                self._stop_event.wait(self._pw_monitor.poll_interval_s)

    def start(self):
        self._pw_monitor.start()
        self._thread.start()

    def stop(self):
        self._pw_monitor.stop()
        self._stop_event.set()

    def is_audio_ready(self):
        return self._pw_monitor.is_audio_ready()

    def get_battery(self):
        with self._lock:
            return dict(self._battery) if self._battery else None
