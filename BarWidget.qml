import QtQuick
import Quickshell
import Quickshell.Io
import qs.Ui

BarWidget {
  id: root
  moduleName: "ubruckhaus.video-trans"
  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight
  Process { id: launcher; command: ["bash", Qt.resolvedUrl("launch.sh").toString().replace(/^file:\/\//, "")] }
  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: "\uf20a"
    tooltipText: "Video Trans — translated video captions"
    onPressed: launcher.running = true
  }
}
