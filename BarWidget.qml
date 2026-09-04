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
  property bool fallbackEnabled: true
  property string error: ""

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

  function labelFor(deviceId) {
    var device = root.devices[deviceId]
    return device && device.label ? device.label : deviceId
  }

  readonly property int activeBattery: batteryFor(root.activeDevice)
  readonly property bool anyConnected: active !== ""

  readonly property string statusLabel: !anyConnected
    ? "No headset active"
    : root.activeLabel + (root.activeBattery >= 0 ? " | " + root.activeBattery + "%" : "")

  readonly property string statusIcon: !anyConnected ? "🎧" // headphone emoji
    : root.activeBattery >= 0 && root.activeBattery <= 15 ? "🪫" // battery-low style marker
    : "🎧"

  readonly property bool opened: panelLoader.item ? panelLoader.item.opened === true : false
  readonly property bool popoutSwitchClosing: panelLoader.item ? panelLoader.item.popoutSwitchClosing === true : false

  function escapeMarkup(value) {
    return String(value || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
  }

  function parseStatusJson(line) {
    var text = String(line || "").trim()
    if (text === "") return
    var parsed
    try {
      parsed = JSON.parse(text)
    } catch (e) {
      root.error = "Bad status output"
      return
    }
    root.active = parsed.active || ""
    root.devices = parsed.devices || {}
    root.priorityOrder = parsed.priority_order || []
    root.fallbackEnabled = parsed.fallback_enabled !== undefined ? !!parsed.fallback_enabled : true
    root.error = parsed.error || ""
  }

  function refresh(quiet) {
    if (statusProcess.running) return
    if (!quiet) loading = true
    statusProcess.running = true
  }

  function setFallbackEnabled(value) {
    if (!root.bar || !root.bar.shell) return
    root.fallbackBusy = true
    // Persisted the same way every first-party panel persists its own
    // settings: merged into this plugin's own shell.json entry, hot-reloaded
    // shell-side, and read directly by the daemon on its next poll - no
    // IPC round trip or sidecar settings file needed.
    root.bar.shell.updateEntryInline(root.moduleName, { settings: { fallbackEnabled: value } })
    root.fallbackEnabled = value
    root.fallbackBusy = false
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

  Process {
    id: statusProcess
    command: [Qt.resolvedUrl("soundmonkey-status").toString().replace("file://", ""), "status"]
    stdout: SplitParser { onRead: function(line) { root.parseStatusJson(line) } }
    onExited: function(exitCode) {
      root.loading = false
    }
  }

  Timer {
    interval: 5000
    repeat: true
    running: true
    triggeredOnStart: true
    onTriggered: root.refresh(true)
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
    tooltipText: root.error !== ""
      ? root.escapeMarkup(root.error)
      : root.escapeMarkup(root.statusLabel)
    onPressed: function(buttonCode) {
      if (buttonCode === Qt.LeftButton) root.toggle()
      else if (buttonCode === Qt.MiddleButton) root.refresh(false)
    }
  }
}
