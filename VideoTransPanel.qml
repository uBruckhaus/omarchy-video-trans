import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui as Ui

Ui.Panel {
  id: root
  moduleName: "ubruckhaus.video-trans"
  manageIpc: false
  property var anchorItem: null
  property var hostWidget: null
  property var config: ({})
  property var sessionState: ({})
  property var deviceOptions: []
  property var modelOptions: []
  property var pending: []
  property var currentRequest: ({})
  property string message: "Ready"
  property bool advanced: false
  property bool appearance: false
  property bool loaded: false
  readonly property bool translating: sessionState.running === true
  readonly property bool stopping: sessionState.stopping === true
  readonly property bool busy: bridge.running && currentRequest.action !== "state"
  function open() { controller.show(); request({action: "state"}) }
  function close() { controller.hide(); request({action: "release"}) }
  function toggle() { opened ? close() : open() }
  function set(key, value) {
    var next = Object.assign({}, config); next[key] = value; config = next
    request({action: "configure", settings: next})
  }
  function selectProvider(value) {
    var next = Object.assign({}, config)
    next.provider = value
    next.endpoint = value === "llama.cpp" ? "http://127.0.0.1:8080" : value === "Ollama" ? "http://127.0.0.1:11434" : "https://api.openai.com/v1"
    next.model = ""; config = next; request({action: "configure", settings: next})
  }
  function request(payload) {
    if (payload.action === "state" && (bridge.running || pending.length)) return
    pending = pending.concat([payload]); nextRequest()
  }
  function nextRequest() {
    if (bridge.running || !pending.length) return
    currentRequest = pending[0]; pending = pending.slice(1); bridge.running = true
  }
  function acceptResponse(text) {
    try {
      var data = JSON.parse(text)
      if (data.error) { message = data.error; return }
      sessionState = data
      if (!pending.length && data.settings && JSON.stringify(config) !== JSON.stringify(data.settings)) config = data.settings
      deviceOptions = (data.outputs || []).map(function(d) { return {value: d.name, label: d.label} })
      modelOptions = data.models || []; message = data.status || "Ready"; loaded = true
    } catch (e) { message = "Cannot read Video Trans response. Run setup.sh." }
  }
  Process {
    id: bridge
    command: ["bash", Qt.resolvedUrl("bridge.sh").toString().replace(/^file:\/\//, "")]
    stdinEnabled: true
    onStarted: write(JSON.stringify(root.currentRequest) + "\n")
    stdout: StdioCollector { onStreamFinished: root.acceptResponse(text) }
    onExited: Qt.callLater(root.nextRequest)
  }
  Timer { interval: 1500; repeat: true; running: root.opened; onTriggered: root.request({action: "state"}) }
  Ui.PopupCard {
    id: popup
    bar: root.bar
    anchorItem: root.anchorItem
    owner: root.hostWidget || root
    open: root.opened
    contentWidth: fittedContentWidth(Style.space(460))
    contentHeight: cappedContentHeight(Style.space(640))
    Flickable {
      anchors.fill: parent
      contentWidth: width
      contentHeight: content.implicitHeight
      clip: true
      boundsBehavior: Flickable.StopAtBounds
      Column {
        id: content
        focus: root.opened
        Keys.onEscapePressed: root.close()
        width: parent.width
        spacing: Style.spacing.md
        Ui.PanelHero {
          title: "Video Trans"
          meta: root.translating ? "Translating · " + (root.config.target || "German") : "Live translated captions"
          iconComponent: Component { Text { text: "\uf20a"; font.family: Style.font.family; font.pixelSize: Style.font.display; color: Color.accent } }
        }
        Row {
          spacing: Style.spacing.md
          Ui.Button { text: root.translating ? "Stop" : "Start"; bordered: true; focusable: true; enabled: root.loaded && !root.stopping && !root.busy; onClicked: root.request({action: root.translating ? "stop" : "start"}) }
          Ui.Button { text: "Show captions"; bordered: true; focusable: true; onClicked: root.request({action: "show"}) }
        }
        Text { width: parent.width; text: root.message; textFormat: Text.PlainText; wrapMode: Text.Wrap; color: Color.popups.text; font.family: Style.font.family; font.pixelSize: Style.font.caption }
        Ui.PanelSeparator {}
        Ui.PanelSectionHeader { text: "Speech and audio" }
        Ui.Dropdown { width: parent.width; label: "Speech provider"; options: ["Whisper (local)"]; value: "Whisper (local)"; enabled: !root.translating }
        Ui.Dropdown { width: parent.width; label: "Input"; options: ["Audio output", "Microphone"]; value: root.config.audio_input || "Audio output"; enabled: !root.translating; onChanged: { root.set("audio_input", value); root.request({action: "outputs"}) } }
        Ui.Dropdown { width: parent.width; label: "Device"; options: root.deviceOptions; value: root.config.output || ""; enabled: !root.translating; onChanged: root.set("output", value) }
        Ui.Dropdown { width: parent.width; label: "Target language"; options: ["German", "English", "French", "Spanish", "Italian", "Portuguese", "Dutch", "Polish", "Ukrainian", "Russian", "Japanese", "Chinese", "Korean", "Arabic", "Hindi", "Turkish", "Indonesian", "Vietnamese"]; value: root.config.target || "German"; enabled: !root.translating; onChanged: root.set("target", value) }
        Ui.PanelSeparator {}
        Ui.PanelSectionHeader { text: "Translation" }
        Ui.Dropdown { width: parent.width; label: "Provider"; options: ["llama.cpp", "Ollama", "Online"]; value: root.config.provider || "llama.cpp"; enabled: !root.translating; onChanged: root.selectProvider(value) }
        Ui.Dropdown { width: parent.width; label: "Model"; options: root.modelOptions.length ? root.modelOptions : [root.config.model || "Select a model"]; value: root.config.model || ""; enabled: !root.translating; onChanged: root.set("model", value) }
        Row {
          spacing: Style.spacing.md
          Ui.Button { text: "Refresh models"; focusable: true; enabled: !root.translating && !root.busy; onClicked: root.request({action: "models"}) }
          Ui.Button { text: "Auto-select local"; focusable: true; enabled: !root.translating && !root.busy; onClicked: root.request({action: "suggest"}) }
        }
        Ui.Button { width: parent.width; text: root.advanced ? "▾ Provider and recognition settings" : "▸ Provider and recognition settings"; leftAlign: true; focusable: true; onClicked: root.advanced = !root.advanced }
        Column {
          width: parent.width; visible: root.advanced; spacing: Style.spacing.md; enabled: !root.translating
          Ui.PanelSectionHeader { text: "Endpoint" }
          Ui.TextField { width: parent.width; text: root.config.endpoint || ""; placeholderText: "Provider base URL"; onEditingFinished: root.set("endpoint", text) }
          Ui.PanelSectionHeader { text: "Model ID (manual entry)" }
          Ui.TextField { width: parent.width; text: root.config.model || ""; placeholderText: "Enter a provider model ID"; onEditingFinished: root.set("model", text) }
          Ui.PanelSectionHeader { text: "API key or bearer token" }
          Ui.TextField { id: token; width: parent.width; password: true; placeholderText: root.sessionState.key_ready ? "Saved token available" : "Enter token" }
          Ui.Toggle { id: remember; width: parent.width; label: "Save token locally"; checked: root.sessionState.remember_token === true; onClicked: { var next = Object.assign({}, root.sessionState); next.remember_token = !checked; root.sessionState = next; root.request({action: "configure", remember_token: !checked}) } }
          Ui.Button { text: "Apply token"; focusable: true; onClicked: { root.request({action: "configure", token: token.text, remember_token: remember.checked}); token.text = "" } }
          Ui.Dropdown { width: parent.width; label: "Source language"; options: ["auto", "en", "de", "fr", "es", "it", "ja", "zh", "ko", "ru", "ar"]; value: root.config.source || "auto"; onChanged: root.set("source", value) }
          Ui.Dropdown { width: parent.width; label: "Whisper model"; options: ["tiny", "base", "small", "medium", "large-v3", "turbo"]; value: root.config.speech_model || "small"; onChanged: root.set("speech_model", value) }
          Ui.Toggle { width: parent.width; label: "Noise suppression"; checked: root.config.noise_filter !== false; onClicked: root.set("noise_filter", !checked) }
          Ui.NumberField { label: "Audio chunk (seconds)"; from: 3; to: 15; value: root.config.chunk_seconds || 5; onModified: root.set("chunk_seconds", value) }
        }
        Ui.PanelSeparator {}
        Ui.Button { width: parent.width; text: root.appearance ? "▾ Caption overlay appearance" : "▸ Caption overlay appearance"; leftAlign: true; focusable: true; onClicked: root.appearance = !root.appearance }
        Column {
          width: parent.width; visible: root.appearance; spacing: Style.spacing.md
          Text { width: parent.width; text: "Only the caption window is affected. −1 uses the Omarchy theme default."; textFormat: Text.PlainText; wrapMode: Text.Wrap; color: Color.popups.text; font.family: Style.font.family; font.pixelSize: Style.font.caption }
          Ui.NumberField { label: "Caption font size"; from: 12; to: 64; value: root.config.font_size || 24; onModified: root.set("font_size", value) }
          Ui.NumberField { label: "Background transparency (%)"; from: -1; to: 100; value: root.config.background_transparency === undefined ? -1 : root.config.background_transparency; onModified: root.set("background_transparency", value) }
          Ui.NumberField { label: "Border thickness (px)"; from: -1; to: 16; value: root.config.border_width === undefined ? -1 : root.config.border_width; onModified: root.set("border_width", value) }
          Ui.NumberField { label: "Retained caption paragraphs"; from: 50; to: 5000; value: root.config.history_lines || 500; onModified: root.set("history_lines", value) }
          Ui.Toggle { width: parent.width; label: "Follow new captions"; checked: root.config.auto_scroll !== false; onClicked: root.set("auto_scroll", !checked) }
          Row { spacing: Style.spacing.md
            Ui.Button { text: "Clear captions"; focusable: true; onClicked: root.request({action: "clear"}) }
            Ui.Button { text: "Close overlay"; focusable: true; onClicked: root.request({action: "close"}) }
          }
        }
      }
    }
  }
}
