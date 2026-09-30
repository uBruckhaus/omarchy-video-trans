import QtQuick
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
  VideoTransPanel { id: panel; bar: root.bar; anchorItem: button; hostWidget: root }
  Ui.BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: "\uf20a"
    tooltipText: "Video Trans — translated video captions"
    onPressed: panel.toggle()
  }
}
