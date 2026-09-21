import QtQuick
import Quickshell
import Quickshell.Io

// Loaded once, kept alive for as long as the plugin is enabled, destroyed
// when it's disabled or removed (see shell.qml's service lifecycle). Owns
// the daemon's install/removal, so end-user install is genuinely just
// `omarchy plugin add <url> --enable` - no terminal steps.
QtObject {
  id: root

  // Resolved once, up front, into plain strings - not computed on demand
  // via a scriptPath() function. Qt.resolvedUrl() needs this component's
  // still-live URL context, which is exactly what's in question during
  // Component.onDestruction (see below); a plain cached string has no such
  // dependency, so reading it at any point in this object's lifetime -
  // including mid-destruction - is safe.
  readonly property string installScript:
    Qt.resolvedUrl("daemon/scripts/ensure-installed.sh").toString().replace("file://", "")
  readonly property string teardownScript:
    Qt.resolvedUrl("daemon/scripts/teardown.sh").toString().replace("file://", "")

  Component.onCompleted: {
    installProcess.running = true
  }

  Component.onDestruction: {
    // Best-effort: Quickshell.execDetached() is a global function, not a
    // property on a child object, and teardownScript is a plain string
    // resolved at construction time - neither needs anything about this
    // object's own live QML context, which is exactly what's unreliable
    // mid-destruction. The previous version of this called
    // `teardownProcess.running = true` (a child Process property) and,
    // separately, called Qt.resolvedUrl() directly inside this handler
    // (via a scriptPath() function) - both threw "Value is null and could
    // not be converted to an object" in practice, confirmed live: QML can
    // tear down child objects and invalidate a component's URL context
    // before or during a parent's Component.onDestruction.
    Quickshell.execDetached([root.teardownScript])
  }

  property Process installProcess: Process {
    command: [root.installScript]
    stdout: SplitParser { onRead: function(line) { console.log("soundmonkey install: " + line) } }
    stderr: SplitParser { onRead: function(line) { console.warn("soundmonkey install: " + line) } }
  }
}
