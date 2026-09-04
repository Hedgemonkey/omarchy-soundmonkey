#!/usr/bin/env python3
"""Generic raw HID report capture, for reverse-engineering an unsupported
device's protocol before writing a DeviceMonitor for it.

Two modes:

  Raw (default): print every report as it arrives, unfiltered - the right
  starting point when you don't yet know which report ID or byte offset
  carries the signal you're after.

  Watch (--watch-offset, requires --report-id): print only when the byte at
  that offset within a matching report changes - once raw mode has shown
  you where the signal lives, this cuts the noise down to state
  transitions. Useful for a marker-synced capture: perform a physical
  action (put the headset on, take an earbud out, power it off), note the
  wall-clock timestamp, and match it against the report that fired at that
  moment - this is how CetraHidMonitor's session-tracking protocol was
  originally reverse-engineered.

Usage:
  hid_capture.py --vid 0x0b05 --pid 0x1ad3
  hid_capture.py --vid 0x0b05 --pid 0x1ad3 --report-id 0x01
  hid_capture.py --vid 0x0b05 --pid 0x1ad3 --report-id 0x01 --watch-offset 5
"""
import argparse
import sys
import time

import hid


def parse_int(value):
    """Accepts decimal or 0x-prefixed hex, matching how VID/PID are usually
    quoted (e.g. by `lsusb`)."""
    return int(value, 0)


def build_parser():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--vid", required=True, type=parse_int, help="USB vendor ID, e.g. 0x0b05")
    parser.add_argument("--pid", required=True, type=parse_int, help="USB product ID, e.g. 0x1ad3")
    parser.add_argument(
        "--report-id", type=parse_int, default=None,
        help="Only print reports whose first byte equals this (required for --watch-offset)")
    parser.add_argument(
        "--watch-offset", type=int, default=None,
        help="Switch to watch mode: only print when the byte at this offset "
             "(within a report matching --report-id) changes")
    parser.add_argument("--timeout-ms", type=int, default=1000)
    return parser


def main():
    args = build_parser().parse_args()

    if args.watch_offset is not None and args.report_id is None:
        build_parser().error("--watch-offset requires --report-id")

    devs = hid.enumerate(args.vid, args.pid)
    if not devs:
        print(f"No HID device found for vid=0x{args.vid:04x} pid=0x{args.pid:04x}", file=sys.stderr)
        sys.exit(1)

    seen = set()
    paths = []
    for d in devs:
        if d["path"] not in seen:
            seen.add(d["path"])
            paths.append(d["path"])
    print(f"Found {len(paths)} distinct HID path(s): {paths}", flush=True)

    dev = hid.Device(path=paths[0])
    print(f"Opened {paths[0]} ({dev.manufacturer} {dev.product})", flush=True)
    print("READY - perform the sequence now. Ctrl+C to stop.", flush=True)

    last_value = None
    try:
        while True:
            data = dev.read(64, timeout=args.timeout_ms)
            if not data:
                continue
            ts = time.strftime("%H:%M:%S")
            report_id = data[0]

            if args.watch_offset is not None:
                if report_id != args.report_id or len(data) <= args.watch_offset:
                    continue
                value = data[args.watch_offset]
                if value == last_value:
                    continue
                last_value = value
                print(
                    f"{ts} report_id=0x{report_id:02x} offset={args.watch_offset} "
                    f"value=0x{value:02x} first8={data[:8].hex()}", flush=True)
                continue

            if args.report_id is not None and report_id != args.report_id:
                continue
            print(f"{ts} report_id={report_id:3d} (0x{report_id:02x}) len={len(data)} bytes={data.hex()}", flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        dev.close()


if __name__ == "__main__":
    main()
