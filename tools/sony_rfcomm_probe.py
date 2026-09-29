#!/usr/bin/env python3
"""Probe a Sony MDR-protocol device's battery opcodes over RFCOMM.

Reimplements the frame format documented by sonyctl
(https://github.com/DaanHessen/sonyctl/blob/master/docs/protocol.md,
confirmed there against a live WH-XB910N) against this repo's target device,
to check whether the same opcode family carries left/right/case battery on a
TWS model instead of the single main-unit battery it carries on an over-ear
model.

Deliberately sends only the documented handshake (`00 00`) and the "get
battery" family (`22 00`, `22 01`, `22 02`) - all reads, never a setter -
per sonyctl's own warning against sweeping opcodes it hasn't confirmed safe.

Usage:
  sony_rfcomm_probe.py --address AC:80:0A:29:4D:FE
  sony_rfcomm_probe.py --address AC:80:0A:29:4D:FE --channel 9
"""
import argparse
import socket
import time

START = 0x3e
END = 0x3c
ESCAPE = 0x3d
ESCAPE_MASK = 0xEF
UNESCAPE_MASK = 0x10

DATA_MDR = 0x0c  # v1 command table - carries battery on every model confirmed so far

SONY_SPP_UUID = "956c7b26-d49a-4ba8-b03f-b17d393cb6e2"


def checksum(body):
    total = 0
    for b in body:
        total = (total + b) & 0xff
    return total


def push_escaped(out, byte):
    if byte in (START, END, ESCAPE):
        out.append(ESCAPE)
        out.append(byte & ESCAPE_MASK)
    else:
        out.append(byte)


def encode_frame(data_type, seq, payload):
    body = bytearray([data_type, seq]) + len(payload).to_bytes(4, "big") + bytes(payload)
    body.append(checksum(body))
    out = bytearray([START])
    for b in body:
        push_escaped(out, b)
    out.append(END)
    return bytes(out)


def unescape(buf):
    out = bytearray()
    it = iter(buf)
    for b in it:
        if b == ESCAPE:
            nxt = next(it, None)
            if nxt is None:
                raise ValueError("truncated escape sequence")
            out.append(nxt | UNESCAPE_MASK)
        else:
            out.append(b)
    return bytes(out)


def decode_frame(buf):
    """Try to pull one complete frame out of the front of buf (a bytearray,
    mutated in place). Returns (data_type, seq, payload) or None."""
    try:
        start = buf.index(START)
    except ValueError:
        return None
    try:
        end_offset = buf.index(END, start + 1)
    except ValueError:
        return None

    raw = buf[start + 1:end_offset]
    del buf[:end_offset + 1]

    unescaped = unescape(raw)
    if len(unescaped) < 7:
        raise ValueError(f"frame too short: {unescaped.hex()}")

    body, checksum_byte = unescaped[:-1], unescaped[-1]
    if checksum(body) != checksum_byte:
        raise ValueError(f"checksum mismatch: {unescaped.hex()}")

    data_type = body[0]
    seq = body[1]
    declared_len = int.from_bytes(body[2:6], "big")
    payload = body[6:]
    if len(payload) != declared_len:
        raise ValueError(f"length mismatch: declared {declared_len}, got {len(payload)}")
    return data_type, seq, payload


class SonyRfcommProbe:
    def __init__(self, sock):
        self.sock = sock
        self.tx_seq = 0
        self.buf = bytearray()

    def _read_frame(self, timeout_s=3.0):
        self.sock.settimeout(timeout_s)
        while True:
            frame = decode_frame(self.buf)
            if frame is not None:
                return frame
            chunk = self.sock.recv(512)
            if not chunk:
                raise ConnectionError("RFCOMM socket closed")
            self.buf.extend(chunk)

    def _write_frame(self, data_type, seq, payload):
        self.sock.sendall(encode_frame(data_type, seq, payload))

    def _ack(self, received_seq):
        self._write_frame(0x01, received_seq ^ 1, b"")

    def request(self, payload, data_type=DATA_MDR):
        """Send a command frame, wait for its ack, then return the next
        non-ack data frame's (data_type, seq, payload) - acking anything
        else (notifications) we see along the way, matching sonyctl's
        send()+recv() pairing."""
        self._write_frame(data_type, self.tx_seq, payload)
        while True:
            dt, seq, pl = self._read_frame()
            if dt == 0x01:  # Ack
                self.tx_seq ^= 1
                break
            self._ack(seq)  # unexpected data frame before our ack; ack and keep waiting

        while True:
            dt, seq, pl = self._read_frame()
            if dt == 0x01:
                continue  # stray ack, ignore
            self._ack(seq)
            return dt, seq, pl


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--address", required=True, help="Device BD address, e.g. AC:80:0A:29:4D:FE")
    parser.add_argument("--channel", type=int, default=9, help="RFCOMM channel (default: 9, per sonyctl's confirmed WH-XB910N)")
    args = parser.parse_args()

    print(f"Connecting to RFCOMM {args.address} channel {args.channel} (UUID {SONY_SPP_UUID})...")
    sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
    sock.connect((args.address, args.channel))
    print("Connected. Settling 400ms before first write (immediate write reliably returns ENOTCONN per sonyctl)...")
    time.sleep(0.4)

    probe = SonyRfcommProbe(sock)

    print("\n--- Handshake: 00 00 (protocol info) ---")
    dt, seq, payload = probe.request(bytes([0x00, 0x00]))
    print(f"  reply dataType=0x{dt:02x} payload={payload.hex()}")

    for sub in (0x00, 0x01, 0x02, 0x03):
        print(f"\n--- Battery get: 22 {sub:02x} ---")
        try:
            dt, seq, payload = probe.request(bytes([0x22, sub]))
            print(f"  reply dataType=0x{dt:02x} payload={payload.hex()}  (len={len(payload)})")
        except Exception as e:
            print(f"  error: {e}")

    sock.close()


if __name__ == "__main__":
    main()
