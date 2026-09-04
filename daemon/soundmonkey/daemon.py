import time
import logging
import os
import json
import yaml

from .monitors import MONITOR_TYPES
from .sink_manager import SinkManager

STATUS_PATH = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "headset-status.json")
SETTINGS_PATH = os.path.expanduser("~/.config/audio-priority-daemon/settings.json")


def build_monitors(cfg):
    """Construct a monitor for each device declared in config.

    Each device names a `type` (a key in monitors.MONITOR_TYPES) and an
    optional `monitor:` dict of kwargs passed straight to that monitor
    class's constructor - kept separate from `sink_match`/`source_match`,
    which are routing config apply_choice()/SinkManager use, not monitor
    construction. Adding a device that fits an existing type is a config-
    only change; this function never needs editing for it. A device with an
    unknown type or invalid monitor kwargs is skipped (logged, not fatal) so
    one bad config entry can't take down detection for every other device.
    """
    devices = cfg.get("devices", {})
    monitors = {}

    for name, dev_cfg in devices.items():
        monitor_type = dev_cfg.get("type")
        monitor_cls = MONITOR_TYPES.get(monitor_type)
        if monitor_cls is None:
            logging.warning(f"{name}: unknown monitor type '{monitor_type}', skipping")
            continue

        kwargs = dev_cfg.get("monitor", {})
        try:
            monitors[name] = monitor_cls(**kwargs)
        except TypeError as e:
            logging.warning(f"{name}: invalid monitor config {kwargs}: {e}")

    return monitors


def decide_choice(monitors, priority_order):
    """Return the highest-priority device whose monitor reports ready, or None."""
    for name in priority_order:
        monitor = monitors.get(name)
        if monitor is not None and monitor.is_audio_ready():
            return name
    return None


def build_status(monitors, choice, fallback_enabled=True):
    """Build the JSON-serialisable status dict written for the bar widget."""
    devices = {}
    for name, monitor in monitors.items():
        battery = monitor.get_battery() if hasattr(monitor, "get_battery") else None
        devices[name] = {
            "connected": monitor.is_audio_ready(),
            "battery": battery,
        }
    return {
        "updated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "active": choice,
        "fallback_enabled": fallback_enabled,
        "devices": devices,
    }


def read_settings(path=SETTINGS_PATH):
    """Read user-toggleable runtime settings, written by the bar widget.

    Defaults to fallback_enabled=True (current behaviour) when the file is
    missing or unreadable, so a fresh install behaves exactly as before.
    """
    try:
        with open(path) as f:
            data = json.load(f)
        return {"fallback_enabled": bool(data.get("fallback_enabled", True))}
    except (OSError, ValueError):
        return {"fallback_enabled": True}


def write_status_file(status, path=STATUS_PATH):
    """Write the status dict atomically so a reader never sees a partial file."""
    tmp_path = path + ".tmp"
    try:
        with open(tmp_path, "w") as f:
            json.dump(status, f)
        os.replace(tmp_path, path)
    except OSError as e:
        logging.warning(f"Could not write status file {path}: {e}")


def apply_choice(sinks, choice, cfg, fallback_enabled=True):
    """Apply sink/source for a device choice, or the fallback when choice is None.

    When choice is None and fallback_enabled is False, this leaves the
    current default sink/source untouched entirely - lets a manual pick
    (PC speakers, a monitor's HDMI audio, etc.) stick instead of being
    overridden by the reassert timer.

    Returns True if a sink was successfully set (or correctly left alone).
    """
    if choice is None:
        if not fallback_enabled:
            return True
        fb = cfg.get("fallback", {})
        mode = fb.get("mode", "system")
        if mode == "system":
            return sinks.set_internal_auto()
        if mode == "match":
            return sinks.set_internal_match(fb.get("substr", ""))
        logging.warning(f"Unknown fallback mode: {mode}")
        return False

    dev_cfg = cfg.get("devices", {}).get(choice, {})
    sink_substr = dev_cfg.get("sink_match")
    source_substr = dev_cfg.get("source_match")

    sink_ok = True
    if sink_substr:
        sink_ok = sinks.set_default_by_description_substr(sink_substr)
    else:
        logging.warning(f"No sink_match configured for {choice}")

    if source_substr:
        sinks.set_default_source_by_description_substr(source_substr)
    else:
        logging.warning(f"No source_match configured for {choice}")

    return sink_ok


def main():
    with open("config.yml") as f:
        cfg = yaml.safe_load(f)

    logging.basicConfig(
        level=getattr(logging, cfg.get("log_level", "INFO")),
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    devices = cfg.get("devices", {})
    monitors = build_monitors(cfg)
    priority_order = cfg.get("priority_order", list(devices.keys()))
    reassert_interval = cfg.get("reassert_interval_s", 30.0)

    for m in monitors.values():
        m.start()

    headset_sink_substrings = [d.get("sink_match") for d in devices.values()]
    sinks = SinkManager(headset_sink_substrings=headset_sink_substrings)
    last_choice = None
    last_apply = 0.0
    last_status = None
    last_status_write = 0.0
    status_heartbeat_s = cfg.get("status_heartbeat_s", 10.0)
    poll_interval = cfg.get("poll_interval_ms", 1000) / 1000.0

    try:
        while True:
            choice = decide_choice(monitors, priority_order)
            settings = read_settings()
            fallback_enabled = settings["fallback_enabled"]
            now = time.time()
            # Apply when the choice changes, or periodically to re-assert in
            # case an external component (e.g. WirePlumber) moved the default.
            # Skip the reassert entirely while fallback is disabled and no
            # headset is active, so a manual sink choice isn't fought.
            should_apply = (choice is not None or fallback_enabled) and (
                (choice != last_choice) or (now - last_apply >= reassert_interval)
            )

            if should_apply:
                if choice != last_choice:
                    label = choice if choice is not None else "fallback"
                    logging.info(f"Audio priority changed: {last_choice} -> {label}")
                apply_choice(sinks, choice, cfg, fallback_enabled=fallback_enabled)
                # Always record the choice so a missing sink does not cause a
                # retry every poll (the re-assert timer handles retries).
                last_choice = choice
                last_apply = now

            status = build_status(monitors, choice, fallback_enabled=fallback_enabled)
            # Write on any state change, and also periodically as a heartbeat
            # so a reader can tell "nothing changed" apart from "daemon died"
            # by checking the file's mtime.
            status_key = (status["devices"], status["fallback_enabled"])
            if status_key != last_status or (now - last_status_write) >= status_heartbeat_s:
                write_status_file(status)
                last_status = status_key
                last_status_write = now

            time.sleep(poll_interval)
    except KeyboardInterrupt:
        logging.info("Daemon exiting")
    finally:
        for m in monitors.values():
            m.stop()


if __name__ == "__main__":
    main()
