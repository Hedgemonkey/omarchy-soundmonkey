# SoundMonkey

Priority-based automatic audio device switching for [Omarchy](https://omarchy.org/),
driven by live headset/earbud presence.

Put your headset on, it becomes the default output. Take it off (or turn it
off), your speakers take over. Have more than one wireless headset? Set a
priority order once and the highest-priority one that's actually on wins -
no manual sink switching, ever.

## What it does

- A background daemon polls each configured device's live connection state
  (via PipeWire, [headsetcontrol](https://github.com/Sapd/HeadsetControl), or
  device-specific USB HID telemetry) and sets the PipeWire default sink/source
  to the highest-priority device that's currently ready.
- A bar widget shows the active device and its battery level, with a panel to
  see every configured device's state at a glance.
- Priority order, per-device enable/disable, and the "fall back to PC
  speakers when nothing's active" toggle are all editable live from the
  panel - no config file editing or daemon restart needed for day-to-day use.

## Install

```
omarchy plugin add https://github.com/hedgemonkey/omarchy-soundmonkey.git --enable
```

That's it. Enabling the plugin builds the daemon's own isolated Python
environment ([uv](https://docs.astral.sh/uv/)-managed, nothing installed
system-wide), seeds a default device config, and starts it as a
`systemd --user` service - no terminal steps beyond the one command above.

## Configure your devices

Edit `~/.config/soundmonkey/config.yml` (seeded on first run from the
plugin's `daemon/config.example.yml`) to declare your own devices. Three
device types are supported out of the box - most devices need no code, just
a config entry:

- `headsetcontrol` - any of the dozens of headsets
  [headsetcontrol](https://github.com/Sapd/HeadsetControl) supports
  (SteelSeries, Corsair, Logitech, Razer, HyperX, and more)
- `pipewire-presence` - any device that just needs "is a matching audio sink
  currently present" (most simple Bluetooth/USB audio devices)
- `cetra-hid` - the ASUS ROG Cetra True Wireless SPEEDNOVA specifically, via
  its raw USB HID protocol (battery + earbud-in/out session state)

Restart the daemon after editing `config.yml` for changes to take effect:
`systemctl --user restart soundmonkey.service`. Priority order, per-device
enable/disable, and the fallback toggle don't need a restart - edit those
live from the bar widget's panel instead.

Don't see your device listed? See [`docs/adding-a-device.md`](docs/adding-a-device.md) -
most devices are a config-only addition, and the rest have a documented path
to reverse-engineering support for them, with tooling included.

## Remove

Disable or remove the plugin (`omarchy plugin remove hedgemonkey.soundmonkey`,
or via the plugin manager UI). This stops and removes the systemd unit.
Your `~/.config/soundmonkey/config.yml` is left in place, in case you
re-enable the plugin later.

## What it touches

- Reads live state via `pw-dump`, `wpctl`, and (for `headsetcontrol`-type
  devices) the `headsetcontrol` CLI - all read-only or scoped to setting the
  PipeWire default sink/source.
- For `cetra-hid`-type devices, reads raw USB HID reports from the matching
  vendor/product ID device via [hidapi](https://github.com/libusb/hidapi) -
  no other USB devices are touched.
- Runs as a `systemd --user` service (`~/.config/systemd/user/soundmonkey.service`),
  installed and removed automatically by the plugin itself.
- Settings (priority order, per-device enable state, fallback toggle) are
  stored in Omarchy's own `~/.config/omarchy/shell.json`, the same mechanism
  every first-party panel uses - nothing bespoke.

## Development

```
cd daemon
uv sync --group dev
uv run pytest
```

See [`docs/adding-a-device.md`](docs/adding-a-device.md) for adding support
for a new device, including the HID reverse-engineering toolkit under `tools/`.

## License

MIT - see [`LICENSE`](LICENSE).
