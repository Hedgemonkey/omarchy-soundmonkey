#!/usr/bin/env python3
"""Live watch of a DeviceMonitor's resolved state - the final verification
step once you've written (or are tweaking) a monitor class for a new
device: confirms is_audio_ready()/get_battery() actually track the real
device correctly, without needing to run the full daemon.

Works with any monitor type in soundmonkey.monitors.MONITOR_TYPES,
including one you've just added and registered there. Run via the
daemon's own environment so `soundmonkey` is importable, e.g. from the
daemon/ directory:

    uv run python ../tools/hid_watch.py --type headsetcontrol \\
        --description-match "Arctis Pro Wireless"

    uv run python ../tools/hid_watch.py --type pipewire-presence \\
        --description-match "WF-1000XM5"

    uv run python ../tools/hid_watch.py --type cetra-hid
"""
import argparse
import time

from soundmonkey.monitors import MONITOR_TYPES


def parse_kwarg(raw):
    key, sep, value = raw.partition("=")
    if not sep:
        raise argparse.ArgumentTypeError(f"expected key=value, got {raw!r}")
    return key, value


def build_parser():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--type", required=True, choices=sorted(MONITOR_TYPES.keys()),
        help="Monitor type to instantiate (a MONITOR_TYPES registry key)")
    parser.add_argument(
        "--description-match", default=None,
        help="Shorthand for the common description_match constructor kwarg")
    parser.add_argument(
        "--kwarg", action="append", type=parse_kwarg, default=[], metavar="KEY=VALUE",
        help="Additional constructor kwarg (repeatable)")
    parser.add_argument("--interval", type=float, default=0.5, help="Poll interval in seconds")
    return parser


def main():
    args = build_parser().parse_args()

    kwargs = dict(args.kwarg)
    if args.description_match is not None:
        kwargs["description_match"] = args.description_match

    monitor_cls = MONITOR_TYPES[args.type]
    monitor = monitor_cls(**kwargs)
    monitor.start()
    print(f"Watching {monitor_cls.__name__}({kwargs}) - waiting for state changes... Ctrl+C to stop.", flush=True)

    last = None
    try:
        while True:
            battery = monitor.get_battery()
            current = (monitor.is_audio_ready(), battery)
            if current != last:
                ts = time.strftime("%H:%M:%S")
                print(f"{ts} audio_ready={current[0]} battery={battery}", flush=True)
                last = current
            time.sleep(args.interval)
    except KeyboardInterrupt:
        pass
    finally:
        monitor.stop()


if __name__ == "__main__":
    main()
