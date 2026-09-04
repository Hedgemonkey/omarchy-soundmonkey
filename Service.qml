import QtQuick
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
    // Best-effort: Process is async, and there's no guarantee the shell
    // waits for it, but this gives the systemd unit its best chance to be
    // stopped and removed cleanly on disable/removal rather than left
    // running orphaned.
    teardownProcess.running = true
  }

  property Process installProcess: Process {
    command: [root.scriptPath("ensure-installed.sh")]
    stdout: SplitParser { onRead: function(line) { console.log("soundmonkey install: " + line) } }
    stderr: SplitParser { onRead: function(line) { console.warn("soundmonkey install: " + line) } }
  }

  property Process teardownProcess: Process {
    command: [root.scriptPath("teardown.sh")]
  }
}
