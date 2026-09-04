import time
import logging
import os
import json
import yaml

from .monitors import MONITOR_TYPES
from .sink_manager import SinkManager
from . import settings as settings_module

STATUS_PATH = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "soundmonkey-status.json")
CONFIG_PATH = os.path.expanduser("~/.config/soundmonkey/config.yml")
PLUGIN_ID = "hedgemonkey.soundmonkey"


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


def decide_choice(monitors, priority_order, enabled_devices=None, current_choice=None):
    """Return the highest-priority enabled device whose monitor reports
    ready, or None.

    enabled_devices: optional {name: bool} (from resolved user settings). A
    device missing from this mapping is treated as enabled, so a device
    added to config.yml but never touched in the panel still works. None
    (the default) means every device in priority_order is considered, for
    callers that don't have settings to apply.

    current_choice: the device currently active, if any. As long as it's
    still enabled and ready, it's kept even if a higher-priority device has
    since also become ready - live-switching a still-working device out
    from under an in-progress use (e.g. a Discord voice call) has reliably
    crashed Discord's WebRTC audio thread, and there's no upside to
    preempting a device that's working fine. Only once current_choice stops
    being ready (or becomes disabled) does normal highest-priority
    selection resume - so putting on a higher-priority headset while a
    lower-priority one is still worn won't switch until the lower-priority
    one is taken off, at which point the higher-priority one wins as usual.
    This does not protect a forced failover (the active device genuinely
    disconnecting) from the same crash risk - that switch still has to
    happen; it just removes the *avoidable* switches.
    """
    if current_choice is not None:
        current_enabled = enabled_devices is None or enabled_devices.get(current_choice, True)
        current_monitor = monitors.get(current_choice)
        if current_enabled and current_monitor is not None and current_monitor.is_audio_ready():
            return current_choice

    for name in priority_order:
        if enabled_devices is not None and not enabled_devices.get(name, True):
            continue
        monitor = monitors.get(name)
        if monitor is not None and monitor.is_audio_ready():
            return name
    return None


class ChoiceDebouncer:
    """Only confirms a decide_choice() result once it has held steady.

    A flapping Bluetooth transport (mid-disconnect/reconnect) can make a
    monitor's readiness flicker several times a second. Applying every one
    of those flickers means WirePlumber relinks live audio streams (e.g.
    Discord's WebRTC voice engine) back-to-back while the underlying device
    is genuinely erroring out, which has reliably aborted Discord's audio
    thread. Requiring the raw choice to be stable for `stable_s` before it
    is acted on absorbs the flicker while still switching promptly on a
    real, sustained change (headset powered off, battery died, etc).
    """

    _UNSET = object()

    def __init__(self, stable_s):
        self.stable_s = stable_s
        self._pending = self._UNSET
        self._pending_since = None
        self._confirmed = None

    def update(self, raw_choice, now):
        if raw_choice != self._pending:
            self._pending = raw_choice
            self._pending_since = now
        if now - self._pending_since >= self.stable_s:
            self._confirmed = self._pending
        return self._confirmed


def build_status(monitors, choice, cfg=None, priority_order=None,
                  enabled_devices=None, fallback_enabled=True):
    """Build the JSON-serialisable status dict written for the bar widget.

    Carries each device's display label (from config.yml's `name:`, falling
    back to the device key), the resolved priority_order, and the resolved
    enabled_devices, so the QML side can render the device list - order,
    labels, current enable state, everything - purely from this payload
    instead of keeping its own hardcoded copy of the device list (the last
    of the original SSoT violations: labels and order used to live only in
    BarWidget.qml/Panel.qml, independently of config.yml) or needing to
    parse shell.json itself just to know what it last wrote there.

    cfg/priority_order/enabled_devices default to None so existing callers
    (and tests) that only care about connected/battery state don't need to
    pass them.
    """
    cfg = cfg or {}
    device_cfgs = cfg.get("devices", {})
    devices = {}
    for name, monitor in monitors.items():
        battery = monitor.get_battery() if hasattr(monitor, "get_battery") else None
        devices[name] = {
            "connected": monitor.is_audio_ready(),
            "battery": battery,
            "label": device_cfgs.get(name, {}).get("name", name),
        }
    return {
        "updated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "active": choice,
        "fallback_enabled": fallback_enabled,
        "priority_order": priority_order or list(monitors.keys()),
        "enabled_devices": enabled_devices if enabled_devices is not None else {},
        "devices": devices,
    }


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
    with open(CONFIG_PATH) as f:
        cfg = yaml.safe_load(f)

    logging.basicConfig(
        level=getattr(logging, cfg.get("log_level", "INFO")),
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    devices = cfg.get("devices", {})
    monitors = build_monitors(cfg)
    reassert_interval = cfg.get("reassert_interval_s", 30.0)

    for m in monitors.values():
        m.start()

    headset_sink_substrings = [d.get("sink_match") for d in devices.values()]
    sinks = SinkManager(headset_sink_substrings=headset_sink_substrings)
    debouncer = ChoiceDebouncer(cfg.get("debounce_s", 2.0))
    last_choice = None
    last_apply = 0.0
    last_status = None
    last_status_write = 0.0
    status_heartbeat_s = cfg.get("status_heartbeat_s", 10.0)
    poll_interval = cfg.get("poll_interval_ms", 1000) / 1000.0

    try:
        while True:
            # Re-resolved every poll so panel edits (reorder, enable/disable,
            # fallback toggle) take effect without a daemon restart.
            resolved = settings_module.resolve_settings(PLUGIN_ID, cfg)
            priority_order = resolved["priorityOrder"]
            enabled_devices = resolved["enabledDevices"]
            fallback_enabled = resolved["fallbackEnabled"]

            now = time.time()
            raw_choice = decide_choice(monitors, priority_order, enabled_devices,
                                        current_choice=last_choice)
            choice = debouncer.update(raw_choice, now)
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

            status = build_status(
                monitors, choice, cfg=cfg, priority_order=priority_order,
                enabled_devices=enabled_devices, fallback_enabled=fallback_enabled,
            )
            # Write on any state change, and also periodically as a heartbeat
            # so a reader can tell "nothing changed" apart from "daemon died"
            # by checking the file's mtime. Includes priority_order/
            # enabled_devices so a panel edit is reflected within one poll
            # interval instead of waiting for the next heartbeat.
            status_key = (
                status["devices"], status["fallback_enabled"],
                status["priority_order"], status["enabled_devices"],
            )
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
