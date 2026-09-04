import QtQuick
import qs.Commons
import qs.Ui

Panel {
  id: root
  moduleName: "hedgemonkey.soundmonkey"
  manageIpc: false

  property var anchorItem: null
  property var hostWidget: null
  readonly property var barIdentity: hostWidget || root
  readonly property color contentForeground: bar ? bar.foreground : Color.foreground
  readonly property string contentFontFamily: bar ? bar.fontFamily : Style.font.family
  readonly property bool busy: hostWidget ? hostWidget.loading : false

  // Device order comes from the daemon's status JSON (config.yml's
  // priority_order, or a live panel reorder once that exists) rather than a
  // second, independently-maintained copy of the device list.
  readonly property var deviceOrder: hostWidget ? hostWidget.priorityOrder : []

  function open() {
    if (hostWidget) hostWidget.refresh(true)
    root.controller.show()
  }

  function close() {
    root.controller.hide()
  }

  function toggle() {
    if (root.opened) root.close()
    else root.open()
  }

  function switchPanel(direction) {
    if (root.bar && typeof root.bar.switchPanelFrom === "function")
      return root.bar.switchPanelFrom(root.barIdentity, direction)
    return false
  }

  function deviceLabel(id) {
    return hostWidget ? hostWidget.labelFor(id) : id
  }

  function deviceInfo(id) {
    if (!hostWidget || !hostWidget.devices[id]) return { connected: false, battery: null }
    return hostWidget.devices[id]
  }

  function batteryText(id) {
    var info = deviceInfo(id)
    if (!info.connected || !info.battery) return ""
    var b = info.battery
    if (typeof b === "number") return b + "%"
    if (b.left !== undefined && b.right !== undefined) {
      var caseText = b.case !== undefined ? (", case " + b.case + "%") : ""
      return "L " + b.left + "% / R " + b.right + "%" + caseText
    }
    return ""
  }

  KeyboardPanel {
    id: panel
    anchorItem: root.anchorItem
    owner: root.barIdentity
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(360))
    contentHeight: panel.fittedContentHeight(content.implicitHeight)

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      onCloseRequested: root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }

      Column {
        id: content
        width: parent.width
        spacing: Style.space(16)

        Row {
          width: parent.width
          spacing: Style.space(14)

          Text {
            anchors.verticalCenter: parent.verticalCenter
            text: hostWidget ? hostWidget.statusIcon : "🎧"
            font.pixelSize: Style.font.displayLarge
          }

          Column {
            width: parent.width - Style.space(90)
            spacing: Style.space(3)

            Text {
              width: parent.width
              text: hostWidget && hostWidget.anyConnected ? hostWidget.activeLabel : "No headset active"
              textFormat: Text.PlainText
              color: root.contentForeground
              font.family: root.contentFontFamily
              font.pixelSize: Style.font.subtitle
              font.bold: true
              elide: Text.ElideRight
            }

            Text {
              width: parent.width
              text: hostWidget && hostWidget.activeBattery >= 0 ? hostWidget.activeBattery + "% battery" : ""
              textFormat: Text.PlainText
              color: Qt.darker(root.contentForeground, 1.45)
              font.family: root.contentFontFamily
              font.pixelSize: Style.font.bodySmall
            }
          }

          PanelActionButton {
            anchors.verticalCenter: parent.verticalCenter
            iconText: root.busy ? "…" : "󰑐"
            tooltipText: "Refresh"
            foreground: root.contentForeground
            fontFamily: root.contentFontFamily
            enabled: !root.busy
            onClicked: if (hostWidget) hostWidget.refresh(false)
          }
        }

        PanelSeparator {
          foreground: root.contentForeground
        }

        Column {
          width: parent.width
          spacing: Style.space(10)

          Repeater {
            model: root.deviceOrder

            Row {
              id: deviceRow
              required property var modelData
              width: parent.width
              spacing: Style.space(10)

              Rectangle {
                anchors.verticalCenter: parent.verticalCenter
                width: Style.space(8)
                height: Style.space(8)
                radius: width / 2
                color: root.deviceInfo(deviceRow.modelData).connected ? Color.accent : Qt.rgba(root.contentForeground.r, root.contentForeground.g, root.contentForeground.b, 0.25)
              }

              Column {
                width: parent.width - Style.space(18)
                spacing: Style.space(2)

                Text {
                  width: parent.width
                  text: root.deviceLabel(deviceRow.modelData)
                  textFormat: Text.PlainText
                  color: root.contentForeground
                  font.family: root.contentFontFamily
                  font.pixelSize: Style.font.body
                  elide: Text.ElideRight
                }

                Text {
                  width: parent.width
                  text: root.deviceInfo(deviceRow.modelData).connected
                    ? (root.batteryText(deviceRow.modelData) || "Connected")
                    : "Not connected"
                  textFormat: Text.PlainText
                  color: Qt.darker(root.contentForeground, 1.45)
                  font.family: root.contentFontFamily
                  font.pixelSize: Style.font.caption
                }
              }
            }
          }
        }

        PanelSeparator {
          foreground: root.contentForeground
        }

        Row {
          width: parent.width
          spacing: Style.space(10)

          Column {
            width: parent.width - Style.space(56)

            Text {
              width: parent.width
              text: "Fall back to PC speakers"
              textFormat: Text.PlainText
              color: root.contentForeground
              font.family: root.contentFontFamily
              font.pixelSize: Style.font.body
            }

            Text {
              width: parent.width
              text: "When off, your manual audio output choice is left alone once no headset is active."
              textFormat: Text.PlainText
              color: Qt.darker(root.contentForeground, 1.45)
              font.family: root.contentFontFamily
              font.pixelSize: Style.font.caption
              wrapMode: Text.WordWrap
            }
          }

          ToggleSwitch {
            id: fallbackSwitch
            anchors.verticalCenter: parent.verticalCenter
            checked: hostWidget ? hostWidget.fallbackEnabled : true
            busy: hostWidget ? hostWidget.fallbackBusy : false
            foreground: root.contentForeground
            onToggled: if (hostWidget) hostWidget.setFallbackEnabled(!checked)
          }
        }

        Text {
          visible: hostWidget && hostWidget.error !== ""
          width: parent.width
          text: hostWidget ? hostWidget.error : ""
          textFormat: Text.PlainText
          color: Color.urgent
          font.family: root.contentFontFamily
          font.pixelSize: Style.font.bodySmall
          wrapMode: Text.WordWrap
        }
      }
    }
  }
}
