import QtQuick
import QtQuick.Controls
import QtQuick.Window
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import Quickshell.Hyprland

ShellRoot {
  id: root
  property var view: ({})
  property bool initialized: false
  property bool initialBorder: true
  property int workspaceId: 0
  property string monitorName: ""
  property int captionWidth: 900
  property int captionHeight: 460
  readonly property int minimumCaptionHeight: Math.ceil(captionMetrics.height * 3 + 28)
  onMinimumCaptionHeightChanged: if (initialized) captionHeight = Math.max(captionHeight, minimumCaptionHeight)
  TextMetrics { id: captionMetrics; font.pointSize: root.view.font_size || 24; text: "Ag" }
  property real left: 100
  property real top: 100
  property var queued: null
  readonly property var workspace: { var id = root.workspaceId; return Hyprland.workspaces.values.find(w => w.id === id) || null }
  readonly property var targetScreen: Quickshell.screens.find(s => s.name === (root.workspace && root.workspace.monitor ? root.workspace.monitor.name : root.monitorName)) || null
  property bool workspaceVisible: false
  function refreshWorkspaceVisibility() {
    var current = Hyprland.workspaces.values.find(w => w.id === root.workspaceId)
    root.workspaceVisible = !!current && current.active
  }

  function accept(data) {
    var next = JSON.parse(data)
    if (!next.theme) return
    view = next
    if (!initialized) {
      var current = Hyprland.focusedWorkspace
      if (!current || !Hyprland.focusedMonitor) return
      workspaceId = current.id
      monitorName = Hyprland.focusedMonitor.name
      captionWidth = next.width || 900
      captionHeight = Math.max(next.height || 460, minimumCaptionHeight)
      left = Math.max(0, (targetScreen.width - captionWidth) / 2)
      top = Math.max(0, targetScreen.height - captionHeight - 60)
      initialized = true
    }
    refreshWorkspaceVisibility()
  }
  Socket {
    id: socket
    path: Quickshell.env("VIDEO_TRANS_SOCKET")
    onConnectedChanged: if (connected) {
      var payload = root.queued || {action: "overlay-state"}
      root.queued = null
      write(JSON.stringify(payload) + "\n")
      flush()
    }
    parser: SplitParser { onRead: data => { socket.connected = false; try { root.accept(data) } catch (e) { console.warn("Caption state unavailable") } } }
  }
  Timer { interval: 250; running: true; repeat: true; triggeredOnStart: true; onTriggered: if (!socket.connected) socket.connected = true }
  Connections {
    target: Hyprland
    function onActiveToplevelChanged() { root.initialBorder = false }
    function onRawEvent(event) { Qt.callLater(root.refreshWorkspaceVisibility) }
  }
  Timer { interval: 1500; running: root.initialized && root.initialBorder; onTriggered: root.initialBorder = false }
  IpcHandler {
    target: "video-trans-overlay"
    function state(): string { return JSON.stringify({visible: panel.visible, workspace: root.workspaceId, width: root.captionWidth, height: root.captionHeight}) }
  }
  PanelWindow {
    id: panel
    screen: root.targetScreen
    visible: root.initialized && root.view.open === true && root.workspaceVisible && root.targetScreen !== null
    anchors { top: true; left: true }
    margins { left: root.left; top: root.top }
    implicitWidth: root.captionWidth
    implicitHeight: root.captionHeight
    color: "transparent"
    mask: Region { item: surface }
    exclusionMode: ExclusionMode.Ignore
    WlrLayershell.namespace: "video-trans-captions"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.OnDemand
    Rectangle {
      id: surface
      anchors.fill: parent
      readonly property var theme: root.view.theme || ({background: "#15171c", foreground: "#e8eaf0", border_color: "#77b8bd"})
      color: Qt.alpha(theme.background, 1 - (root.view.background_transparency === undefined ? 100 : root.view.background_transparency) / 100)
      border.width: root.view.border_width === undefined ? 1 : root.view.border_width
      border.color: Window.active || root.initialBorder ? theme.border_color : "transparent"
      Connections { target: surface.Window.window; function onActiveChanged() { root.initialBorder = false } }
      // Changing focus only changes border color, preserving caption geometry.
      Flickable {
        id: scroll
        anchors.fill: parent
        anchors.margins: 14
        clip: true
        contentWidth: width
        contentHeight: captions.height
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar {}
        TextEdit {
          id: captions
          width: scroll.width
          height: Math.max(scroll.height, implicitHeight)
          text: root.view.text || (root.view.caption_received ? "" : root.view.status || "Starting captions…")
          textFormat: TextEdit.PlainText
          wrapMode: TextEdit.Wrap
          readOnly: true
          selectByMouse: true
          color: surface.theme.foreground
          font.pointSize: root.view.font_size || 24
          onTextChanged: if (root.view.auto_scroll !== false) Qt.callLater(() => scroll.contentY = Math.max(0, scroll.contentHeight - scroll.height))
        }
      }
      // Capture plain left drags even over the fully transparent caption area.
      MouseArea {
        id: moveArea
        anchors.fill: parent
        preventStealing: true
        acceptedButtons: Qt.LeftButton
        cursorShape: pressed ? Qt.ClosedHandCursor : Qt.OpenHandCursor
        property point initial
        property point pointer
        onPressed: mouse => {
          if (mouse.modifiers & Qt.ShiftModifier) { mouse.accepted = false; return }
          initial = Qt.point(root.left, root.top)
          pointer = mapToGlobal(mouse.x, mouse.y)
          root.initialBorder = false
        }
        onPositionChanged: mouse => {
          if (!pressed) return
          var position = mapToGlobal(mouse.x, mouse.y)
          root.left = Math.max(0, Math.min(root.targetScreen.width - 60, initial.x + position.x - pointer.x))
          root.top = Math.max(0, Math.min(root.targetScreen.height - 60, initial.y + position.y - pointer.y))
        }
        onWheel: wheel => {
          scroll.contentY = Math.max(0, Math.min(scroll.contentHeight - scroll.height, scroll.contentY - wheel.angleDelta.y / 2))
          wheel.accepted = true
        }
      }
      Canvas {
        id: resizeHandle
        anchors { bottom: parent.bottom; right: parent.right; margins: 4 }
        width: 28; height: 28
        onPaint: {
          var context = getContext("2d")
          context.clearRect(0, 0, width, height)
          context.strokeStyle = surface.theme.foreground
          context.lineWidth = 2
          for (var offset of [7, 13, 19]) { context.beginPath(); context.moveTo(26 - offset, 24); context.lineTo(24, 26 - offset); context.stroke() }
        }
        Connections { target: surface; function onThemeChanged() { resizeHandle.requestPaint() } }
        MouseArea {
          anchors.fill: parent
          cursorShape: Qt.SizeFDiagCursor
          property point initial
          property point pointer
          onPressed: mouse => { initial = Qt.point(root.captionWidth, root.captionHeight); pointer = mapToGlobal(mouse.x, mouse.y) }
          onPositionChanged: mouse => {
            if (!pressed) return
            var position = mapToGlobal(mouse.x, mouse.y)
            root.captionWidth = Math.max(430, Math.min(root.targetScreen.width - root.left, initial.x + position.x - pointer.x))
            root.captionHeight = Math.max(root.minimumCaptionHeight, Math.min(root.targetScreen.height - root.top, initial.y + position.y - pointer.y))
          }
          onReleased: root.queued = {action: "overlay-geometry", width: root.captionWidth, height: root.captionHeight}
        }
      }
    }
  }
}
