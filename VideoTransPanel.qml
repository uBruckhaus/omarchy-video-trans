import QtQuick
import QtQuick.Controls as Controls
import Quickshell
import Quickshell.Io
import "native/Commons"
import qs.Commons as Theme
import "native/Ui" as Ui

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
  property bool showManualView: false
  onShowManualViewChanged: panelScroll.contentY = 0
  readonly property bool translating: sessionState.running === true
  readonly property bool stopping: sessionState.stopping === true
  readonly property bool downloading: sessionState.downloading === true
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
    contentHeight: fittedContentHeight(content.implicitHeight)
    Flickable {
      id: panelScroll
      anchors.fill: parent
      contentWidth: width
      contentHeight: content.implicitHeight
      clip: true
      boundsBehavior: Flickable.StopAtBounds
      Controls.ScrollBar.vertical: Controls.ScrollBar { policy: Controls.ScrollBar.AsNeeded }
      Column {
        id: content
        focus: root.opened
        Keys.onEscapePressed: root.close()
        width: parent.width
        spacing: Style.space(12)
        Item {
          width: parent.width
          height: Style.space(28)
          Text {
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            text: "Video Trans"
            color: Theme.Color.accent
            font.family: Theme.Style.font.family
            font.pixelSize: Theme.Style.font.title
            font.bold: true
          }
          Ui.Button {
            id: manualButton
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            implicitHeight: Style.space(24)
            text: root.showManualView ? "✕ Close Manual" : "📖 User Manual"
            fontSize: Style.font.caption
            bordered: true
            focusable: true
            selected: root.showManualView
            tooltipText: "Open or close the integrated Video Trans User Manual"
            onClicked: root.showManualView = !root.showManualView
          }
        }
        Text {
          width: parent.width
          text: root.showManualView ? "Live translated captions." : root.sessionState.starting ? "Starting translation…" : root.translating ? "Translating · " + (root.config.target || "German") : "Live translated captions"
          color: Color.foreground
          opacity: 0.65
          font.family: Style.font.family
          font.pixelSize: Style.font.body
          wrapMode: Text.Wrap
        }
        Column {
          width: parent.width
          spacing: Style.spacing.md
          visible: !root.showManualView
        Row {
          spacing: Style.spacing.md
          Ui.Button { text: root.translating ? "Stop" : "Start"; bordered: true; focusable: true; enabled: root.loaded && !root.stopping && !root.busy && !root.downloading; onClicked: root.request({action: root.translating ? "stop" : "start"}) }
          Ui.Button { text: "Show captions"; bordered: true; focusable: true; onClicked: root.request({action: "show"}) }
          Ui.Button { text: "Clear captions"; focusable: true; onClicked: root.request({action: "clear"}) }
        }
        Ui.Toggle { width: parent.width; label: "Follow new captions"; checked: root.config.auto_scroll !== false; onClicked: root.set("auto_scroll", !checked) }
        Ui.NumberField { label: "Caption duration (seconds)"; from: 1; to: 120; value: root.config.caption_seconds || 5; onModified: root.set("caption_seconds", value) }
        Ui.NumberField { label: "Caption font size"; from: 12; to: 64; value: root.config.font_size || 24; onModified: root.set("font_size", value) }
        Text { width: parent.width; text: root.message; textFormat: Text.PlainText; wrapMode: Text.Wrap; color: Color.popups.text; font.family: Style.font.family; font.pixelSize: Style.font.caption }
        Column {
          width: parent.width
          spacing: Style.spacing.sm
          visible: (root.sessionState.checks || []).length > 0
          Ui.PanelSectionHeader { text: "Startup check" }
          Repeater {
            model: root.sessionState.checks || []
            delegate: Row {
              required property var modelData
              width: parent.width
              spacing: Style.spacing.sm
              Text { width: Style.space(20); text: modelData.status === "checking" ? "…" : "✓"; color: modelData.status === "ok" ? "#66c98b" : modelData.status === "error" ? "#f16b72" : Color.popups.text; font.family: Style.font.family; font.pixelSize: Style.font.body }
              Text { width: parent.width - Style.space(28); text: modelData.label + ": " + modelData.detail; textFormat: Text.PlainText; wrapMode: Text.Wrap; color: Color.popups.text; font.family: Style.font.family; font.pixelSize: Style.font.caption }
            }
          }
        }
        Ui.PanelSeparator {}
        Ui.PanelSectionHeader { text: "Speech and audio" }
        Ui.Dropdown { width: parent.width; label: "Speech provider"; options: ["Whisper (local)"]; value: "Whisper (local)"; enabled: !root.translating && !root.downloading }
        Ui.Dropdown { width: parent.width; label: "Whisper model"; options: [{value: "tiny", label: "Tiny"}, {value: "base", label: "Base"}, {value: "small", label: "Small"}, {value: "medium", label: "Medium"}, {value: "large-v3", label: "Large (big, v3)"}, {value: "turbo", label: "Turbo"}]; value: root.config.speech_model || "small"; enabled: !root.translating && !root.downloading; onChanged: root.set("speech_model", value) }
        Ui.Button { text: root.downloading ? "Cancel Whisper download" : "Download selected Whisper model"; focusable: true; enabled: !root.translating && !root.stopping && !root.busy; onClicked: root.request({action: root.downloading ? "cancel-download" : "download"}) }
        Ui.Dropdown { width: parent.width; label: "Input"; options: ["Audio output", "Microphone"]; value: root.config.audio_input || "Audio output"; enabled: !root.translating && !root.downloading; onChanged: { root.set("audio_input", value); root.request({action: "outputs"}) } }
        Ui.Dropdown { width: parent.width; label: "Device"; options: root.deviceOptions; value: root.config.output || ""; enabled: !root.translating && !root.downloading; onChanged: root.set("output", value) }
        Ui.Dropdown { width: parent.width; label: "Target language"; options: ["German", "English", "French", "Spanish", "Italian", "Portuguese", "Dutch", "Polish", "Ukrainian", "Russian", "Japanese", "Chinese", "Korean", "Arabic", "Hindi", "Turkish", "Indonesian", "Vietnamese"]; value: root.config.target || "German"; enabled: !root.translating && !root.downloading; onChanged: root.set("target", value) }
        Ui.PanelSeparator {}
        Ui.PanelSectionHeader { text: "Translation" }
        Ui.Dropdown { width: parent.width; label: "Provider"; options: ["llama.cpp", "Ollama", "Online"]; value: root.config.provider || "llama.cpp"; enabled: !root.translating && !root.downloading; onChanged: root.selectProvider(value) }
        Ui.Dropdown { width: parent.width; label: "Model"; options: root.modelOptions.length ? root.modelOptions : [root.config.model || "Select a model"]; value: root.config.model || ""; enabled: !root.translating && !root.downloading; onChanged: root.set("model", value) }
        Row {
          spacing: Style.spacing.md
          Ui.Button { text: "Refresh models"; focusable: true; enabled: !root.translating && !root.downloading && !root.busy; onClicked: root.request({action: "models"}) }
          Ui.Button { text: "Auto-select local"; focusable: true; enabled: !root.translating && !root.downloading && !root.busy; onClicked: root.request({action: "suggest"}) }
        }
        Ui.Button { width: parent.width; text: root.advanced ? "▾ Provider and recognition settings" : "▸ Provider and recognition settings"; leftAlign: true; focusable: true; onClicked: root.advanced = !root.advanced }
        Column {
          width: parent.width; visible: root.advanced; spacing: Style.spacing.md; enabled: !root.translating && !root.downloading
          Ui.PanelSectionHeader { text: "Endpoint" }
          Ui.TextField { width: parent.width; text: root.config.endpoint || ""; placeholderText: "Provider base URL"; onEditingFinished: root.set("endpoint", text) }
          Ui.PanelSectionHeader { text: "Model ID (manual entry)" }
          Ui.TextField { width: parent.width; text: root.config.model || ""; placeholderText: "Enter a provider model ID"; onEditingFinished: root.set("model", text) }
          Ui.PanelSectionHeader { text: "API key or bearer token" }
          Ui.TextField { id: token; width: parent.width; password: true; placeholderText: root.sessionState.key_ready ? "Token configured" : "Enter token" }
          Ui.Toggle { id: remember; width: parent.width; label: "Save token locally"; checked: root.sessionState.remember_token === true; onClicked: { var desired = !checked; var next = Object.assign({}, root.sessionState); next.remember_token = desired; root.sessionState = next; root.request({action: "configure", remember_token: desired}) } }
          Ui.Button { text: "Apply token"; focusable: true; onClicked: { root.request({action: "configure", token: token.text, remember_token: remember.checked}); token.text = "" } }
          Ui.Dropdown { width: parent.width; label: "Source language"; options: ["auto", "en", "de", "fr", "es", "it", "ja", "zh", "ko", "ru", "ar"]; value: root.config.source || "auto"; onChanged: root.set("source", value) }
          Ui.Toggle { width: parent.width; label: "Noise suppression"; checked: root.config.noise_filter !== false; onClicked: root.set("noise_filter", !checked) }
          Ui.NumberField { label: "Audio chunk (seconds)"; from: 3; to: 15; value: root.config.chunk_seconds || 5; onModified: root.set("chunk_seconds", value) }
        }
        Ui.PanelSeparator {}
        Ui.Button { width: parent.width; text: root.appearance ? "▾ Caption overlay appearance" : "▸ Caption overlay appearance"; leftAlign: true; focusable: true; onClicked: root.appearance = !root.appearance }
        Column {
          width: parent.width; visible: root.appearance; spacing: Style.spacing.md
          Text { width: parent.width; text: "Only the caption window is affected. −1 uses the Omarchy theme default."; textFormat: Text.PlainText; wrapMode: Text.Wrap; color: Color.popups.text; font.family: Style.font.family; font.pixelSize: Style.font.caption }
          Ui.NumberField { label: "Background transparency (%)"; from: -1; to: 100; value: root.config.background_transparency === undefined ? -1 : root.config.background_transparency; onModified: root.set("background_transparency", value) }
          Ui.NumberField { label: "Border thickness (px)"; from: -1; to: 16; value: root.config.border_width === undefined ? -1 : root.config.border_width; onModified: root.set("border_width", value) }
          Ui.NumberField { label: "Retained caption paragraphs"; from: 50; to: 5000; value: root.config.history_lines || 500; onModified: root.set("history_lines", value) }
          Row { spacing: Style.spacing.md
            Ui.Button { text: "Close overlay"; focusable: true; onClicked: root.request({action: "close"}) }
          }
        }
        }
        Column {
          width: parent.width
          spacing: Style.space(10)
          visible: root.showManualView
          Ui.Button { width: parent.width; text: "← Back to Video Trans Controls"; bordered: true; focusable: true; onClicked: root.showManualView = false }
          Repeater {
            model: [
              {
                            "title": "1. First Session (Speech & Audio)",
                            "body": "• Run setup.sh once before using the plugin.\n• Play your video, choose Audio output and its playback device.\n• For microphone speech, select Microphone and its device explicitly.\n• Keep source language on auto; choose a multilingual Whisper model and target language.\n• Download the speech model now, or let Start download it when needed."
              },
              {
                            "title": "2. Translation Provider",
                            "body": "• Choose llama.cpp, Ollama or Online.\n• Refresh models and choose a text model, or use Auto-select local.\n• Local providers require an existing installation and models.\n• For Online, expand Provider and recognition settings, enter endpoint, model and token, then Apply token.\n• Save token locally is optional."
              },
              {
                            "title": "3. Start, Stop & Session Controls",
                            "body": "• Start begins capture and opens the caption window.\n• Check the startup checklist and status for missing requirements.\n• Closing the popup leaves translation running with a visible overlay.\n• Stop or Close overlay ends capture and releases owned resources.\n• Show captions opens the window without capture; Clear captions removes its text."
              },
              {
                            "title": "4. Caption Window & Mouse Controls",
                            "body": "• Left-drag moves the window; the bottom-right handle resizes it.\n• Shift + drag selects caption text.\n• Scroll to read older captions; disable Follow new captions to pause automatic scrolling.\n• The overlay stays above fullscreen video on the workspace where it opened."
              },
              {
                            "title": "5. Reading & Overlay Appearance",
                            "body": "• Caption duration sets how long each paragraph remains visible (default 5 seconds).\n• Caption font size can change during translation.\n• Overlay appearance adjusts transparency, border and retained history.\n• −1 uses theme defaults. These settings affect only the captions."
              },
              {
                            "title": "6. Troubleshooting & Privacy",
                            "body": "• No captions: check the selected playback device, startup checks and status.\n• Wrong language: use a multilingual Whisper model or override the source language.\n• Slow captions: try smaller recognition or translation models.\n• Audio stays local; recognized text goes to your selected translator.\n• Saved tokens are owner-only plaintext. Cleanup may wait for a provider request."
              }
]
            delegate: Rectangle {
              required property var modelData
              width: parent.width
              implicitHeight: manualSection.implicitHeight + Style.space(16)
              radius: Style.space(6)
              color: Qt.rgba(Color.foreground.r, Color.foreground.g, Color.foreground.b, 0.05)
              border.width: 1
              border.color: Qt.rgba(Color.foreground.r, Color.foreground.g, Color.foreground.b, 0.15)
              Column {
                id: manualSection
                anchors.fill: parent
                anchors.margins: Style.space(8)
                spacing: Style.space(4)
                Text {
                  width: parent.width
                  text: modelData.title
                  textFormat: Text.PlainText
                  color: Theme.Color.accent
                  font.family: Style.font.family
                  font.pixelSize: Theme.Style.font.bodySmall
                  font.bold: true
                  wrapMode: Text.Wrap
                }
                Text {
                  width: parent.width
                  text: modelData.body
                  textFormat: Text.PlainText
                  color: Color.foreground
                  opacity: 0.85
                  font.family: Style.font.family
                  font.pixelSize: Style.font.caption
                  wrapMode: Text.Wrap
                }
              }
            }
          }
          Ui.Button { width: parent.width; text: "← Back to Video Trans Controls"; bordered: true; focusable: true; onClicked: root.showManualView = false }
        }
      }
    }
  }
}
