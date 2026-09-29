import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

BarWidget {
  id: root
  moduleName: "hedgemonkey.soundmonkey"

  property bool loading: false
  property bool fallbackBusy: false
  property string active: ""
  property var devices: ({})
  property var priorityOrder: []
  property var enabledDevices: ({})
  property bool fallbackEnabled: true
  property string error: ""
  property bool reorderBusy: false

  // Device display labels and ordering come from the daemon's status JSON
  // (itself driven by config.yml's `name:` per device, and the resolved
  // priority order after any live panel edits) rather than being duplicated
  // here - there is exactly one place that knows the device list.
  readonly property var activeDevice: active !== "" && devices[active] ? devices[active] : null
  readonly property string activeLabel: activeDevice && activeDevice.label ? activeDevice.label : active

  function batteryFor(device) {
    if (!device || !device.battery) return -1
    var b = device.battery
    if (typeof b === "number") return b
    // Cetra-style {left, right, case}: the weaker earbud is the limiting factor
    if (b.left !== undefined && b.right !== undefined) return Math.min(b.left, b.right)
    return -1
  }

  // Full per-device battery text: "62%" for a single-cell device, or
  // "L 62% / R 58%, case 71%" for a left/right(/case) device - used
  // anywhere the whole reading matters, unlike batteryFor()'s single
  // worst-case number (which only drives the low-battery icon threshold).
  function formatBattery(battery) {
    if (!battery) return ""
    if (typeof battery === "number") return battery + "%"
    if (battery.left !== undefined && battery.right !== undefined) {
      var text = "L " + battery.left + "% / R " + battery.right + "%"
      if (battery.case !== undefined) text += ", case " + battery.case + "%"
      return text
    }
    return ""
  }

  function labelFor(deviceId) {
    var device = root.devices[deviceId]
    return device && device.label ? device.label : deviceId
  }

  readonly property int activeBattery: batteryFor(root.activeDevice)
  readonly property string activeBatteryText: formatBattery(root.activeDevice && root.activeDevice.battery)
  readonly property bool anyConnected: active !== ""

  readonly property string statusLabel: !anyConnected
    ? "No headset active"
    : root.activeLabel + (root.activeBatteryText !== "" ? " | " + root.activeBatteryText : "")

  readonly property string statusIcon: !anyConnected ? "🎧" // headphone emoji
    : root.activeBattery >= 0 && root.activeBattery <= 15 ? "🪫" // battery-low style marker
    : "🎧"

  readonly property bool opened: panelLoader.item ? panelLoader.item.opened === true : false
  readonly property bool popoutSwitchClosing: panelLoader.item ? panelLoader.item.popoutSwitchClosing === true : false

  function escapeMarkup(value) {
    return String(value || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
  }

  // The daemon writes its own local timestamp into every status write
  // (including plain heartbeats with no other change), so staleness -
  // "the daemon has stopped updating this file" - is derived from that
  // field rather than re-deriving it from the status file's own mtime via
  // an external `stat` call the way the old soundmonkey-status shell
  // script did.
  readonly property int staleAfterMs: 25000
  property double lastUpdatedMs: 0

  function parseStatusJson(text) {
    var raw = String(text || "").trim()
    if (raw === "") return
    var parsed
    try {
      parsed = JSON.parse(raw)
    } catch (e) {
      root.error = "Bad status output"
      return
    }
    root.active = parsed.active || ""
    root.devices = parsed.devices || {}
    root.priorityOrder = parsed.priority_order || []
    root.enabledDevices = parsed.enabled_devices || {}
    root.fallbackEnabled = parsed.fallback_enabled !== undefined ? !!parsed.fallback_enabled : true
    root.error = parsed.error || ""

    root.lastUpdatedMs = 0
    if (parsed.updated) {
      var parsedMs = Date.parse(parsed.updated)
      if (!isNaN(parsedMs)) root.lastUpdatedMs = parsedMs
    }
    root.checkStale()
  }

  function checkStale() {
    if (root.lastUpdatedMs === 0) return
    if (Date.now() - root.lastUpdatedMs > root.staleAfterMs) {
      root.error = "daemon stalled"
      root.active = ""
    }
  }

  function refresh(quiet) {
    if (!quiet) loading = true
    statusFile.reload()
  }

  function isDeviceEnabled(deviceId) {
    // A device the user has never touched in the panel is absent from
    // enabledDevices, not false - matches decide_choice()'s own default.
    return root.enabledDevices[deviceId] !== false
  }

  function persistSettings(patch) {
    if (!root.bar || !root.bar.shell) return
    // Persisted the same way every first-party panel persists its own
    // settings: merged into this plugin's own shell.json entry, hot-reloaded
    // shell-side, and read directly by the daemon on its next poll - no IPC
    // round trip or sidecar settings file needed. Always sends the complete
    // current object for whichever keys it touches (not a sparse diff), so
    // there's no ambiguity about whether the shell deep-merges nested values.
    root.bar.shell.updateEntryInline(root.moduleName, { settings: patch })
  }

  function setFallbackEnabled(value) {
    root.fallbackBusy = true
    persistSettings({ fallbackEnabled: value })
    root.fallbackEnabled = value
    root.fallbackBusy = false
  }

  function setDeviceEnabled(deviceId, enabled) {
    var updated = Object.assign({}, root.enabledDevices)
    updated[deviceId] = enabled
    persistSettings({ enabledDevices: updated })
    root.enabledDevices = updated
  }

  function moveDevicePriority(deviceId, direction) {
    // direction: -1 (up / higher priority) or +1 (down / lower priority).
    var order = root.priorityOrder.slice()
    var index = order.indexOf(deviceId)
    var target = index + direction
    if (index < 0 || target < 0 || target >= order.length) return

    root.reorderBusy = true
    var swap = order[target]
    order[target] = order[index]
    order[index] = swap
    persistSettings({ priorityOrder: order })
    root.priorityOrder = order
    root.reorderBusy = false
  }

  function open() {
    refresh(true)
    if (panelLoader.item) panelLoader.item.open()
  }

  function close() {
    if (panelLoader.item) panelLoader.item.close()
  }

  function toggle() {
    if (panelLoader.item) panelLoader.item.toggle()
  }

  function closeForPopoutSwitch() {
    if (panelLoader.item) panelLoader.item.closeForPopoutSwitch()
  }

  function injectPanel() {
    if (!panelLoader.item) return
    panelLoader.item.bar = root.bar
    panelLoader.item.anchorItem = button
    panelLoader.item.hostWidget = root
  }

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  onBarChanged: injectPanel()

  readonly property string statusFilePath: {
    var runtimeDir = Quickshell.env("XDG_RUNTIME_DIR")
    return (runtimeDir && runtimeDir !== "" ? runtimeDir : "/tmp") + "/soundmonkey-status.json"
  }

  // Watches the daemon's status file directly instead of spawning
  // `soundmonkey-status status` on a fixed timer: a connect/disconnect is
  // reflected here as soon as the daemon's next write lands (inotify-driven,
  // typically well under a second) rather than waiting for the next poll
  // tick, which previously added up to 5s of pure latency on top of the
  // daemon's own detection time.
  FileView {
    id: statusFile
    path: root.statusFilePath
    watchChanges: true
    printErrors: false
    onFileChanged: reload()
    onLoaded: {
      root.parseStatusJson(text())
      root.loading = false
    }
    onLoadFailed: function(error) {
      root.loading = false
      root.active = ""
      root.devices = {}
      root.lastUpdatedMs = 0
      root.error = "daemon not running"
    }
  }

  Timer {
    // Backstops watchChanges: guards against a lost/never-armed file watch
    // (e.g. inotify quota exhaustion) and re-evaluates staleness even when
    // the daemon has died outright and stopped writing entirely, neither of
    // which would ever produce another fileChanged() on their own.
    interval: 10000
    repeat: true
    running: true
    onTriggered: statusFile.reload()
  }

  Loader {
    id: panelLoader
    active: true
    source: Qt.resolvedUrl("Panel.qml")
    visible: false
    onLoaded: {
      root.injectPanel()
      Qt.callLater(root.injectPanel)
    }
  }

  IpcHandler {
    target: root.moduleName
    function inspect(): string {
      return JSON.stringify({
        active: root.active,
        devices: root.devices,
        priorityOrder: root.priorityOrder,
        fallbackEnabled: root.fallbackEnabled,
        error: root.error
      })
    }
    function refresh(): void { root.refresh(false) }
    function open(): void { root.open() }
    function close(): void { root.close() }
    function show(): void { root.open() }
    function hide(): void { root.close() }
    function toggle(): void { root.toggle() }
  }

  WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: root.statusIcon
    dimmed: !root.anyConnected
    active: root.anyConnected
    activeColor: root.activeBattery >= 0 && root.activeBattery <= 15 ? Color.urgent : Color.accent
    tooltipText: root.error !== ""
      ? root.escapeMarkup(root.error)
      : root.escapeMarkup(root.statusLabel)
    onPressed: function(buttonCode) {
      if (buttonCode === Qt.LeftButton) root.toggle()
      else if (buttonCode === Qt.MiddleButton) root.refresh(false)
    }
  }

  // statusIcon is a color-emoji glyph ("🎧"/"🪫"), and color-emoji fonts
  // render their own embedded palette regardless of the Text `color`
  // property - so WidgetButton's active/activeColor tinting above has no
  // visible effect on it. A small badge is the only way to actually show
  // connected state on this icon.
  Rectangle {
    visible: root.anyConnected
    width: 6
    height: 6
    radius: 3
    color: root.activeBattery >= 0 && root.activeBattery <= 15 ? Color.urgent : Color.accent
    border.width: 1
    border.color: Color.background
    anchors.right: button.right
    anchors.bottom: button.bottom
    anchors.rightMargin: 1
    anchors.bottomMargin: 1
  }
}
