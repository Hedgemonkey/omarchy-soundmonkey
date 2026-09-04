import json
import os

SHELL_CONFIG_PATH = os.path.expanduser("~/.config/omarchy/shell.json")

_BAR_SECTIONS = ("left", "center", "right")


def _find_plugin_entry(shell_cfg, plugin_id):
    """Search bar.layout.{left,center,right}[] and plugins[] for the entry
    matching plugin_id. Returns the entry dict, or None if not found."""
    bar_layout = shell_cfg.get("bar", {}).get("layout", {})
    for section in _BAR_SECTIONS:
        for entry in bar_layout.get(section, []):
            if entry.get("id") == plugin_id:
                return entry

    for entry in shell_cfg.get("plugins", []):
        if entry.get("id") == plugin_id:
            return entry

    return None


def read_user_settings(plugin_id, path=SHELL_CONFIG_PATH):
    """Read this plugin's user-editable settings (priority order, per-device
    enabled flag, fallback toggle) from Omarchy's shell.json - the same file
    and mechanism (`shell.updateEntryInline`) first-party panels already use
    to persist their own settings, so the panel's edits are hot-reloaded
    shell-side and survive a shell restart for free. No bespoke sidecar
    settings file needed.

    Returns {} when shell.json is missing, malformed, or has no entry (or no
    "settings" object) for this plugin yet - callers layer config.yml-derived
    defaults over whatever keys are present here (see resolve_settings),
    rather than requiring this to be complete.
    """
    try:
        with open(path) as f:
            shell_cfg = json.load(f)
    except (OSError, ValueError):
        return {}

    entry = _find_plugin_entry(shell_cfg, plugin_id)
    if entry is None:
        return {}

    settings = entry.get("settings")
    return settings if isinstance(settings, dict) else {}


def resolve_settings(plugin_id, cfg, path=SHELL_CONFIG_PATH):
    """Merge user settings (from shell.json) over config.yml-derived
    defaults.

    Defaults (used for any key the user hasn't touched in the panel yet):
    priorityOrder from cfg['priority_order'] (or declaration order of
    cfg['devices'] if unset), every configured device enabled, and
    fallback enabled. A key present in shell.json's settings for this
    plugin always wins over the default.
    """
    devices = cfg.get("devices", {})
    defaults = {
        "priorityOrder": cfg.get("priority_order", list(devices.keys())),
        "enabledDevices": {name: True for name in devices},
        "fallbackEnabled": True,
    }
    user = read_user_settings(plugin_id, path=path)
    return {**defaults, **user}
