# Adding a device

SoundMonkey detects devices through pluggable `DeviceMonitor` classes,
looked up by a `type:` key in `config.yml` (see
`daemon/soundmonkey/monitors/__init__.py`'s `MONITOR_TYPES` registry).
Most new devices need **no new code at all** - just a config entry. Work
through this in order:

## 1. Does `headsetcontrol` already support it?

[headsetcontrol](https://github.com/Sapd/HeadsetControl) supports dozens of
headsets (SteelSeries, Corsair, Logitech, Razer, HyperX, and more). Check:

```bash
headsetcontrol --output json
```

If your device shows up there, add a config entry using `type: headsetcontrol`
- no code needed:

```yaml
devices:
  MY_HEADSET:
    name: "My Headset"
    type: headsetcontrol
    sink_match: "My Headset Analog Stereo"   # substring of the PipeWire sink name
    source_match: "My Headset Mono"
    monitor:
      description_match: "My Headset"        # substring of headsetcontrol's own device name
```

## 2. Does it just need "is a matching sink present"?

Some devices (most simple Bluetooth/USB audio devices with no useful session
telemetry) are adequately detected by "does a PipeWire sink with this
description exist right now" - the device shows up when active, and
disappears when not. Use `type: pipewire-presence`:

```yaml
devices:
  MY_SPEAKER:
    name: "My Bluetooth Speaker"
    type: pipewire-presence
    sink_match: "My Bluetooth Speaker"
    monitor:
      description_match: "My Bluetooth Speaker"
```

Check with `pw-dump | grep -i "your device"` (while it's connected) to find
the right substring.

If it's a Bluetooth device, it reports battery level automatically, no
config needed: the matched PipeWire sink node already carries its own
`api.bluez5.address` prop, which the monitor reuses to ask BlueZ's
`org.bluez.Battery1` (via `bluetoothctl info`) for the percentage - same
as any headset that reports battery over AVRCP/HFP. Confirm yours does
with `bluetoothctl info <mac>` (from `bluetoothctl devices Connected`)
while connected - look for a `Battery Percentage:` line. If your device
doesn't have one, `get_battery()` just stays unsupported, same as before
this existed.

If you ever need to point battery polling at a *different* address than
the one on the matched sink (rare - e.g. a multi-node device where the
matched sink isn't the node BlueZ tracks battery on), pass `mac_address:`
explicitly and it takes priority over auto-detection:

```yaml
    monitor:
      description_match: "My Bluetooth Speaker"
      mac_address: "AA:BB:CC:DD:EE:FF"
```

## 3. Otherwise: reverse-engineer a new monitor type

If neither of the above fits - the device needs vendor-specific raw HID
reports for battery level, wear/session state, or anything else PipeWire and
headsetcontrol don't expose - you'll need a new `DeviceMonitor` subclass.
`monitors/cetra_hid.py` (CetraHidMonitor) is a full worked example of this,
including its own reverse-engineering notes in its docstring.

**Capture the protocol.** Find the device's USB VID/PID (`lsusb`), then:

```bash
# From daemon/, using the project's own environment:
uv run python ../tools/hid_capture.py --vid 0xXXXX --pid 0xYYYY
```

This dumps every raw HID report as it arrives. Perform the physical action
you care about (put the headset on, take an earbud out, power it off) and
watch for reports that correlate with it. A **marker-synced capture** works
well: note the wall-clock timestamp right as you perform the action, then
match it against the report that fired at that moment.

Once you've spotted a candidate report ID and byte offset, narrow in with
watch mode, which only prints when that byte changes:

```bash
uv run python ../tools/hid_capture.py --vid 0xXXXX --pid 0xYYYY \
  --report-id 0xNN --watch-offset N
```

**Write the monitor.** Subclass `DeviceMonitor`
(`daemon/soundmonkey/monitors/base.py`) implementing `start()`, `stop()`,
`is_audio_ready()`, and optionally `get_battery()`. If the device also needs
a "does a sink exist" check (most do, for coarse presence detection
alongside your device-specific telemetry), compose a `PipewirePresenceMonitor`
internally rather than duplicating the `pw-dump` polling loop - see
`CetraHidMonitor` for the pattern.

**Register it** in `MONITOR_TYPES` (`monitors/__init__.py`) under a new
type name.

**Verify it live** before writing tests:

```bash
uv run python ../tools/hid_watch.py --type my-new-type --description-match "My Device"
```

This instantiates your monitor and prints `is_audio_ready()`/`get_battery()`
every time either changes, so you can confirm it tracks the real device
correctly without running the full daemon.

**Add tests.** Every existing monitor has a dedicated test file
(`tests/test_*_monitor.py`) covering its detection logic without needing the
real device connected (report bytes are hand-constructed, `pw-dump`/
`headsetcontrol` output is mocked). Follow the same pattern.

**Open a PR** with the new monitor, its tests, and a `config.example.yml`
entry (or a note in the README) showing how to configure it.
