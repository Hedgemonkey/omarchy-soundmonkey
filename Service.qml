import QtQuick
import Quickshell
import Quickshell.Io

// Loaded once, kept alive for as long as the plugin is enabled, destroyed
// when it's disabled or removed (see shell.qml's service lifecycle). Owns
// the daemon's install/removal, so end-user install is genuinely just
// `omarchy plugin add <url> --enable` - no terminal steps.
QtObject {
  id: root

  function scriptPath(name) {
    return Qt.resolvedUrl("daemon/scripts/" + name).toString().replace("file://", "")
  }

  Component.onCompleted: {
    installProcess.running = true
  }

  Component.onDestruction: {
    // Best-effort: Quickshell.execDetached() is a global function, not a
    // property on a child object - unlike the previous version of this
    // (a declared `property Process teardownProcess`), it doesn't need
    // this object's own properties to still be valid mid-destruction.
    // Referencing a child Process property here threw "Value is null and
    // could not be converted to an object" in practice: QML tears down
    // child objects before (or concurrently with) running a parent's
    // Component.onDestruction, so `teardownProcess` could already be gone.
    Quickshell.execDetached([root.scriptPath("teardown.sh")])
  }

  property Process installProcess: Process {
    command: [root.scriptPath("ensure-installed.sh")]
    stdout: SplitParser { onRead: function(line) { console.log("soundmonkey install: " + line) } }
    stderr: SplitParser { onRead: function(line) { console.warn("soundmonkey install: " + line) } }
  }
}
