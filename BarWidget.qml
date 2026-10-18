import QtQuick
import Quickshell
import Quickshell.Io
import qs.Ui as Ui

Ui.BarWidget {
  id: root
  moduleName: "ubruckhaus.video-trans"
  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight
  readonly property bool opened: panel.opened
  readonly property bool popoutSwitchClosing: panel.popoutSwitchClosing
  function open() { panel.open() }
  function close() { panel.close() }
  function closeForPopoutSwitch() { panel.closeForPopoutSwitch() }

  // Translating (or starting): the icon turns the theme's green.
  property bool running: false
  property string target: ""
  property color green: "#66c98b"
  function accept(state) {
    running = state.running === true || state.starting === true
    if (state.settings && state.settings.target) target = state.settings.target
  }
  Connections { target: panel; function onSessionStateChanged() { root.accept(panel.sessionState) } }

  // Ask the controller over its owner-only socket. Connect only when the socket exists:
  // no socket means Video Trans is not running, and failed connects would fill the shell log.
  readonly property string runtimeDir: Quickshell.env("XDG_RUNTIME_DIR") || "/tmp"
  property string uid: (runtimeDir.match(/\/run\/user\/(\d+)$/) || ["", ""])[1]
  Process {
    running: root.uid === ""
    command: ["id", "-u"]
    stdout: StdioCollector { onStreamFinished: root.uid = text.trim() }
  }
  Socket {
    id: controller
    path: root.uid ? root.runtimeDir + "/video-trans-" + root.uid + ".sock" : ""
    // "brief": only running/starting/target, a small fixed-shape reply (no model list or status text).
    function ask() { write('{"action":"brief","keep":true}\n'); flush() }
    onConnectionStateChanged: if (connected) ask()
    // The connection stays open while Video Trans runs; it only ends when the controller exits.
    // Quickshell sets connected back to false by itself; setting it here, inside the error
    // signal of a closed connection, makes quickshell 0.3.2 free the socket twice and crash.
    onError: root.running = false
    parser: SplitParser {
      onRead: function(line) {
        try { root.accept(JSON.parse(line)) } catch (e) {}
      }
    }
  }
  Process {
    id: probe
    command: ["test", "-S", controller.path]
    onExited: function(code) {
      if (code !== 0) root.running = false
      else if (!controller.connected) controller.connected = true
    }
  }
  Timer {
    interval: 2000; repeat: true; running: true; triggeredOnStart: true
    onTriggered: {
      if (controller.connected) controller.ask()
      else if (controller.path && !probe.running) probe.running = true
    }
  }
  // The tray icon Launch & Bind lists under "Running in the bar". One per session:
  // tray.py holds a lock, so instances on other monitors exit at once. Without the
  // runtime tray.sh exits too; retry so the tray appears after setup.
  Process {
    id: tray
    command: ["bash", Qt.resolvedUrl("tray.sh").toString().replace(/^file:\/\//, "")]
    running: true
  }
  Timer { interval: 30000; repeat: true; running: true; onTriggered: if (!tray.running) tray.running = true }
  FileView {
    path: (Quickshell.env("XDG_STATE_HOME") || Quickshell.env("HOME") + "/.local/state") + "/omarchy/current/theme/colors.toml"
    watchChanges: true
    onFileChanged: reload()
    onLoaded: {
      var match = text().match(/^\s*green\s*=\s*"(#[0-9a-fA-F]{6})"/m)
      if (match) root.green = match[1]
    }
  }

  VideoTransPanel { id: panel; bar: root.bar; anchorItem: button; hostWidget: root }
  Ui.BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: ""
    active: root.running
    activeColor: root.green
    tooltipText: "Video Trans · " + (root.running ? "translating" + (root.target ? " → " + root.target : "") : "off") +
                 "\nClick: caption controls · Right-click: " + (root.running ? "stop" : "start") + " captions"
    onPressed: function(button) {
      if (button === Qt.RightButton) panel.request({action: root.running ? "stop" : "start"})
      else panel.toggle()
    }
  }
}
