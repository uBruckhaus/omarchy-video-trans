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
  property bool loaded: false
  property bool showManualView: false
  property bool showProvider: false
  property bool showListeningGroup: false
  property bool showTranslationGroup: false
  property bool showCaptionsGroup: false
  property bool showRecognitionOptions: false
  property bool showAppearance: false
  property bool showMoreFixes: false
  onShowManualViewChanged: panelScroll.contentY = 0
  onShowProviderChanged: panelScroll.contentY = 0
  readonly property bool translating: sessionState.running === true
  readonly property bool starting: sessionState.starting === true
  readonly property bool stopping: sessionState.stopping === true
  readonly property bool downloading: sessionState.downloading === true
  readonly property bool busy: bridge.running && currentRequest.action !== "state"
  readonly property bool locked: translating || downloading || setupBusy
  readonly property var setupState: sessionState.setup || ({})
  readonly property bool setupBusy: setupState.busy === true
  readonly property var steps: sessionState.steps || []
  readonly property var failedSteps: steps.filter(function(s) { return !s.ok })
  readonly property var nextStep: loaded && failedSteps.length ? failedSteps[0] : null
  onNextStepChanged: showMoreFixes = false
  readonly property bool runtimeReady: loaded && !steps.some(function(s) { return s.id === "runtime" && !s.ok })
  readonly property bool ready: loaded && steps.length > 0 && failedSteps.length === 0
  readonly property var languages: ["German", "English", "French", "Spanish", "Italian", "Portuguese", "Dutch", "Polish", "Ukrainian", "Russian", "Japanese", "Chinese", "Korean", "Arabic", "Hindi", "Turkish", "Indonesian", "Vietnamese"]
  // Caption colour choices come from the controller (core.TEXT_COLORS); the fallback keeps the
  // picker usable before the first answer.
  readonly property var textColorOptions: sessionState.text_colors && sessionState.text_colors.length ? sessionState.text_colors : [{value: "auto", label: "Automatic · white or black for the video behind"}, {value: "theme", label: "Omarchy theme"}, {value: "white", label: "White"}, {value: "black", label: "Black"}]
  readonly property string textColorLabel: {
    for (var i = 0; i < textColorOptions.length; i++) if (textColorOptions[i].value === config.text_color) return textColorOptions[i].label
    return config.text_color || "auto"
  }
  readonly property var whisperModels: [{value: "tiny", label: "Tiny · 75 MB · fastest"}, {value: "base", label: "Base · 145 MB"}, {value: "small", label: "Small · 480 MB · recommended"}, {value: "medium", label: "Medium · 1.5 GB"}, {value: "large-v3", label: "Large v3 · 3 GB · most accurate"}, {value: "turbo", label: "Turbo · 1.6 GB · large and fast"}]
  readonly property string deviceLabel: {
    for (var i = 0; i < deviceOptions.length; i++) if (deviceOptions[i].value === config.output) return deviceOptions[i].label
    return "no device chosen"
  }
  readonly property string summary: "Active: " + (config.audio_input || "Audio output") + " · " + deviceLabel + "\n" +
    "Whisper " + (config.speech_model || "small") + " → " + (config.target || "German") + " · " + (config.provider || "llama.cpp") +
    (config.model ? " · " + config.model : "") + " · " +
    (starting ? "Starting…" : translating ? "Translating" : ready ? "Ready" : "Setup needed")
  function stepFor(id) {
    for (var i = 0; i < steps.length; i++) if (steps[i].id === id) return steps[i]
    return null
  }
  function stepNote(id, done) {
    var item = stepFor(id)
    return item && !item.ok ? item.problem : "✓ " + done
  }
  function open() { controller.show(); request({action: "state"}) }
  function close() { controller.hide(); request({action: "release"}) }
  function toggle() { opened ? close() : open() }
  // Backspace on a subpage returns to the caption controls (text fields keep it).
  function goBack() {
    if (showManualView) showManualView = false
    else if (showProvider) showProvider = false
    else return false
    content.forceActiveFocus()
    return true
  }
  function apply(changes) {
    var next = Object.assign({}, config, changes); config = next
    request({action: "configure", settings: next})
  }
  function set(key, value) { var changes = {}; changes[key] = value; apply(changes) }
  function selectProvider(value) {
    apply({provider: value, model: "", endpoint: value === "llama.cpp" ? "http://127.0.0.1:8080" : value === "Ollama" ? "http://127.0.0.1:11434" : "https://api.openai.com/v1"})
    if (value === "Online") showProvider = true
  }
  function applyFix(fix) {
    if (fix.settings) apply(fix.settings)
    if (fix.action) request({action: fix.action})
    if (fix.settings && fix.settings.audio_input) request({action: "outputs"})
    if (fix.panel === "provider") showProvider = true
  }
  // Explicit paste (Ctrl+V) for text fields: the bridge reads the clipboard bounded.
  property var pasteTarget: null
  function pasteInto(field) { pasteTarget = field; request({action: "paste"}) }
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
      if (currentRequest.action === "paste") {
        if (pasteTarget && data.clipboard) pasteTarget.insert(data.clipboard)
        pasteTarget = null
        return
      }
      sessionState = data
      if (!pending.length && data.settings && JSON.stringify(config) !== JSON.stringify(data.settings)) config = data.settings
      deviceOptions = (data.outputs || []).map(function(d) { return {value: d.name, label: d.label} })
      modelOptions = data.models || []
      message = (data.setup && (data.setup.busy || data.setup.phase === "error")) ? data.setup.message : data.status || "Ready"
      loaded = true
    } catch (e) { message = "Cannot read Video Trans response." }
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

  // A collapsible group card: icon, title, one-line summary and a chevron.
  component GroupCard: Rectangle {
    id: group
    property string icon: ""
    property string title: ""
    property string summary: ""
    property bool expanded: false
    signal toggled()
    default property alias body: groupBody.data
    width: parent.width
    height: groupColumn.implicitHeight + Style.space(20)
    radius: Style.cornerRadius
    color: Qt.rgba(Color.foreground.r, Color.foreground.g, Color.foreground.b, 0.04)
    border.color: Qt.rgba(Color.foreground.r, Color.foreground.g, Color.foreground.b, 0.14)
    Column {
      id: groupColumn
      anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: Style.space(10)
      spacing: Style.spacing.md
      Item {
        width: parent.width; height: Math.max(groupTitle.implicitHeight, Style.space(22))
        Row {
          anchors.left: parent.left; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
          spacing: Style.space(8)
          Text { text: group.icon; color: Theme.Color.accent; font.family: Style.font.family; font.pixelSize: Style.font.body + Style.space(4); anchors.verticalCenter: parent.verticalCenter }
          Text { id: groupTitle; text: group.title; color: Theme.Color.accent; font.family: Style.font.family; font.pixelSize: Style.font.body; font.bold: true; anchors.verticalCenter: parent.verticalCenter }
          Text { text: "· " + group.summary; textFormat: Text.PlainText; color: Color.foreground; opacity: 0.7; elide: Text.ElideRight; width: parent.width - Style.space(150); font.family: Style.font.family; font.pixelSize: Style.font.caption; anchors.verticalCenter: parent.verticalCenter }
        }
        Text { anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; text: group.expanded ? "▾" : "▸"; color: Theme.Color.accent; font.family: Style.font.family; font.pixelSize: Style.font.body }
        MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: group.toggled() }
      }
      Column { id: groupBody; width: parent.width; spacing: Style.spacing.md; visible: group.expanded }
    }
  }
  component Note: Text {
    width: parent.width; textFormat: Text.PlainText; wrapMode: Text.Wrap
    color: Color.foreground; opacity: 0.8; font.family: Style.font.family; font.pixelSize: Style.font.caption
  }

  // A layer-shell panel that takes the keyboard when it opens; an xdg-popup
  // (PopupCard) never receives keys, so text fields stayed dead.
  Ui.KeyboardPanel {
    id: popup
    focusTarget: content
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
        width: parent.width
        spacing: Style.space(12)
        Keys.onEscapePressed: root.close()
        Keys.onPressed: function(event) {
          if (event.key === Qt.Key_Backspace && root.goBack()) event.accepted = true
        }
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
        Text { width: parent.width; text: "Live translated captions from video, calls or your microphone."; color: Color.foreground; opacity: 0.65; font.family: Style.font.family; font.pixelSize: Style.font.body; wrapMode: Text.Wrap }

        Column {
          width: parent.width
          spacing: Style.spacing.md
          visible: !root.showManualView && !root.showProvider
          Rectangle {
            width: parent.width
            height: summaryText.implicitHeight + Style.space(20)
            radius: Style.cornerRadius
            color: Qt.rgba(Theme.Color.accent.r, Theme.Color.accent.g, Theme.Color.accent.b, 0.12)
            border.color: Theme.Color.accent
            Text { id: summaryText; anchors.fill: parent; anchors.margins: Style.space(10); text: root.summary; textFormat: Text.PlainText; wrapMode: Text.Wrap; color: Color.foreground; font.family: Style.font.family; font.pixelSize: Style.font.body; font.bold: true }
          }
          Row {
            width: parent.width; spacing: Style.spacing.md
            Ui.Button { focusable: true; width: (parent.width - 2 * Style.spacing.md) / 3; text: "▶  Start"; tooltipText: "Start captions (desktop action: Start captions)"; bordered: true; selected: enabled; enabled: root.ready && !root.translating && !root.stopping && !root.busy && !root.downloading; onClicked: root.request({action: "start"}) }
            Ui.Button { focusable: true; width: (parent.width - 2 * Style.spacing.md) / 3; text: "■  Stop"; tooltipText: "Stop captions and free models"; bordered: true; selected: root.translating; enabled: (root.translating || root.sessionState.overlay === true) && !root.stopping; onClicked: root.request({action: "stop"}) }
            Ui.Button { focusable: true; width: (parent.width - 2 * Style.spacing.md) / 3; text: "Captions"; tooltipText: "Show the caption window without capturing"; bordered: true; enabled: root.runtimeReady; onClicked: root.request({action: "show"}) }
          }
          Rectangle {
            width: parent.width
            visible: !root.translating && (root.nextStep !== null || root.setupBusy || root.downloading)
            height: visible ? stepColumn.implicitHeight + Style.space(20) : 0
            radius: Style.cornerRadius
            color: Qt.rgba(Theme.Color.accent.r, Theme.Color.accent.g, Theme.Color.accent.b, 0.10)
            border.color: Theme.Color.accent
            Column {
              id: stepColumn
              anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: Style.space(10)
              spacing: Style.spacing.md
              Text { width: parent.width; text: root.setupBusy ? "Setting up…" : root.downloading ? "Downloading Whisper…" : "Not ready yet" + (root.failedSteps.length > 1 ? " · step 1 of " + root.failedSteps.length : ""); color: Theme.Color.accent; font.family: Style.font.family; font.pixelSize: Style.font.body; font.bold: true }
              Text { width: parent.width; text: root.setupBusy ? root.setupState.message : root.downloading ? root.message : (root.setupState.phase === "error" && root.nextStep && root.nextStep.id === "runtime" ? root.setupState.message + "\n" : "") + (root.nextStep ? root.nextStep.problem : ""); textFormat: Text.PlainText; wrapMode: Text.Wrap; color: Color.foreground; font.family: Style.font.family; font.pixelSize: Style.font.body }
              Ui.Button { focusable: true; width: parent.width; visible: !root.setupBusy && !root.downloading && root.nextStep !== null && root.nextStep.fixes.length > 0; selected: true; bordered: true; enabled: !root.busy; text: visible ? root.nextStep.fixes[0].label : ""; onClicked: root.applyFix(root.nextStep.fixes[0]) }
              Ui.Button { focusable: true; visible: root.downloading; bordered: true; text: "Cancel download"; onClicked: root.request({action: "cancel-download"}) }
              Text { visible: !root.setupBusy && !root.downloading && root.nextStep !== null && root.nextStep.fixes.length > 1; text: root.showMoreFixes ? "▾ Other options" : "▸ Other options"; color: Theme.Color.accent; font.family: Style.font.family; font.pixelSize: Style.font.caption
                MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: root.showMoreFixes = !root.showMoreFixes } }
              Flow {
                width: parent.width; spacing: Style.spacing.md; visible: root.showMoreFixes && !root.setupBusy && !root.downloading && root.nextStep !== null
                Repeater {
                  model: root.nextStep ? root.nextStep.fixes.slice(1) : []
                  Ui.Button { required property var modelData; focusable: true; bordered: true; enabled: !root.busy; text: modelData.label; fontSize: Style.font.caption; onClicked: root.applyFix(modelData) }
                }
              }
            }
          }
          Note { visible: root.ready && !root.translating && !root.starting; text: "✓ Ready. Play your video or call, then press ▶ Start." }
          Note { text: "Status: " + root.message; opacity: 1 }
          Column {
            width: parent.width
            spacing: Style.spacing.sm
            visible: (root.sessionState.checks || []).length > 0 && (root.starting || (root.sessionState.checks || []).some(function(c) { return c.status === "error" }))
            Ui.PanelSectionHeader { text: "Startup check" }
            Repeater {
              model: root.sessionState.checks || []
              delegate: Row {
                required property var modelData
                width: parent.width
                spacing: Style.spacing.sm
                Text { width: Style.space(20); text: modelData.status === "checking" ? "…" : modelData.status === "error" ? "✕" : "✓"; color: modelData.status === "ok" ? "#66c98b" : modelData.status === "error" ? "#f16b72" : Color.popups.text; font.family: Style.font.family; font.pixelSize: Style.font.body }
                Text { width: parent.width - Style.space(28); text: modelData.label + ": " + modelData.detail; textFormat: Text.PlainText; wrapMode: Text.Wrap; color: Color.popups.text; font.family: Style.font.family; font.pixelSize: Style.font.caption }
              }
            }
          }

          GroupCard {
            icon: "󰋋"
            title: "Listening"
            summary: (root.config.audio_input || "Audio output") + " · Whisper " + (root.config.speech_model || "small")
            expanded: root.showListeningGroup
            onToggled: root.showListeningGroup = !root.showListeningGroup
            Ui.Dropdown { id: capturePicker; width: parent.width; label: "Capture"; options: [{value: "Audio output", label: "Audio output · what you hear (video, calls)"}, {value: "Microphone", label: "Microphone · speech in the room"}]; value: root.config.audio_input || "Audio output"; enabled: root.runtimeReady && !root.locked; onChanged: { root.apply({audio_input: value, output: ""}); root.request({action: "outputs"}); capturePicker.value = Qt.binding(function() { return root.config.audio_input || "Audio output" }) } }
            Ui.Dropdown { id: devicePicker; width: parent.width; label: "Device"; options: root.deviceOptions.length ? root.deviceOptions : [{value: "", label: "No device found"}]; value: root.config.output || ""; enabled: root.runtimeReady && !root.locked; onChanged: { root.set("output", value); devicePicker.value = Qt.binding(function() { return root.config.output || "" }) } }
            Ui.Dropdown { id: whisperPicker; width: parent.width; label: "Speech recognition · Whisper model"; options: root.whisperModels; value: root.config.speech_model || "small"; enabled: root.runtimeReady && !root.locked; onChanged: { root.set("speech_model", value); whisperPicker.value = Qt.binding(function() { return root.config.speech_model || "small" }) } }
            Note { text: root.stepNote("whisper", "Whisper " + (root.config.speech_model || "small") + " is downloaded. Audio stays on this computer.") }
            Ui.Button { focusable: true; width: parent.width; visible: root.stepFor("whisper") !== null && !root.stepFor("whisper").ok || root.downloading; bordered: true; selected: !root.downloading; text: root.downloading ? "Cancel Whisper download" : "󰇚  Download Whisper " + (root.config.speech_model || "small"); enabled: root.runtimeReady && !root.translating && !root.stopping && !root.busy; onClicked: root.request({action: root.downloading ? "cancel-download" : "download"}) }
            Ui.Button { focusable: true; width: parent.width; text: root.showRecognitionOptions ? "▾ Recognition options" : "▸ Recognition options"; bordered: true; onClicked: root.showRecognitionOptions = !root.showRecognitionOptions }
            Column {
              width: parent.width; spacing: Style.spacing.md; visible: root.showRecognitionOptions; enabled: root.runtimeReady && !root.locked
              Ui.Dropdown { id: sourcePicker; width: parent.width; label: "Spoken language"; options: [{value: "auto", label: "Detect automatically"}, {value: "en", label: "English"}, {value: "de", label: "German"}, {value: "fr", label: "French"}, {value: "es", label: "Spanish"}, {value: "it", label: "Italian"}, {value: "ja", label: "Japanese"}, {value: "zh", label: "Chinese"}, {value: "ko", label: "Korean"}, {value: "ru", label: "Russian"}, {value: "ar", label: "Arabic"}]; value: root.config.source || "auto"; enabled: root.runtimeReady && !root.locked; onChanged: { root.set("source", value); sourcePicker.value = Qt.binding(function() { return root.config.source || "auto" }) } }
              Ui.Toggle { width: parent.width; label: "Noise suppression"; checked: root.config.noise_filter !== false; onClicked: root.set("noise_filter", !checked) }
              Ui.NumberField { label: "Audio chunk (seconds)"; from: 3; to: 15; value: root.config.chunk_seconds || 5; onModified: root.set("chunk_seconds", value) }
              Note { text: "Shorter chunks show captions sooner; longer chunks give Whisper more context." }
            }
          }

          GroupCard {
            icon: "󰗊"
            title: "Translation"
            summary: "→ " + (root.config.target || "German") + " · " + (root.config.provider || "llama.cpp") + (root.config.model ? " · " + root.config.model : "")
            expanded: root.showTranslationGroup
            onToggled: root.showTranslationGroup = !root.showTranslationGroup
            Ui.SearchableDropdown { id: targetPicker; width: parent.width; placeholderText: "Type to filter languages…"; label: "Translate into"; options: root.languages.map(function(l) { return {value: l, label: l} }); value: root.config.target || "German"; enabled: root.runtimeReady && !root.locked; onChanged: { root.set("target", value); targetPicker.value = Qt.binding(function() { return root.config.target || "German" }) } }
            Ui.Dropdown { id: providerPicker; width: parent.width; label: "Translator"; options: [{value: "llama.cpp", label: "llama.cpp · local"}, {value: "Ollama", label: "Ollama · local"}, {value: "Online", label: "Online · OpenAI-compatible server"}]; value: root.config.provider || "llama.cpp"; enabled: root.runtimeReady && !root.locked; onChanged: { root.selectProvider(value); providerPicker.value = Qt.binding(function() { return root.config.provider || "llama.cpp" }) } }
            Note { text: root.stepNote("provider", (root.config.provider || "llama.cpp") + (root.config.provider === "Online" ? " is configured." : " is available; Start launches it when needed.")) }
            Ui.SearchableDropdown { id: modelPicker; width: parent.width; placeholderText: "Type to filter models…"; label: "Model"; options: root.modelOptions.length ? root.modelOptions.map(function(m) { return {value: m, label: m} }) : [{value: root.config.model || "", label: root.config.model || "Load the model list or choose automatically"}]; value: root.config.model || ""; enabled: root.runtimeReady && !root.locked; onChanged: { root.set("model", value); modelPicker.value = Qt.binding(function() { return root.config.model || "" }) } }
            Flow {
              width: parent.width; spacing: Style.spacing.md
              Ui.Button { focusable: true; text: "Choose automatically"; bordered: true; visible: root.config.provider !== "Online"; tooltipText: "Pick an installed model that suits the target language"; enabled: root.runtimeReady && !root.locked && !root.busy; onClicked: root.request({action: "suggest"}) }
              Ui.Button { focusable: true; text: "Load model list"; bordered: true; enabled: root.runtimeReady && !root.locked && !root.busy; onClicked: root.request({action: "models"}) }
              Ui.Button { focusable: true; text: "Provider settings…"; bordered: true; onClicked: root.showProvider = true }
            }
          }

          GroupCard {
            icon: ""
            title: "Captions"
            summary: (root.config.font_size || 24) + " px · " + (root.config.caption_seconds || 5) + " s" + (root.config.text_color && root.config.text_color !== "auto" && root.config.text_color !== "theme" ? " · " + root.textColorLabel.toLowerCase() + " text" : "") + (root.config.auto_scroll === false ? " · paused" : "")
            expanded: root.showCaptionsGroup
            onToggled: root.showCaptionsGroup = !root.showCaptionsGroup
            Flow {
              width: parent.width; spacing: Style.spacing.md
              Ui.Button { focusable: true; text: "Clear captions"; bordered: true; enabled: root.runtimeReady; onClicked: root.request({action: "clear"}) }
              Ui.Button { focusable: true; text: "Close caption window"; bordered: true; enabled: root.sessionState.overlay === true; onClicked: root.request({action: "close"}) }
            }
            Ui.Toggle { width: parent.width; label: "Follow new captions"; checked: root.config.auto_scroll !== false; onClicked: root.set("auto_scroll", !checked) }
            Ui.Dropdown { id: textColorPicker; width: parent.width; label: "Caption text colour · backdrop adapts for contrast"; options: root.textColorOptions; value: root.config.text_color || "auto"; onChanged: { root.set("text_color", value); textColorPicker.value = Qt.binding(function() { return root.config.text_color || "auto" }) } }
            Ui.NumberField { label: "Show each caption for (seconds)"; from: 1; to: 120; value: root.config.caption_seconds || 5; onModified: root.set("caption_seconds", value) }
            Ui.NumberField { label: "Caption font size"; from: 12; to: 64; value: root.config.font_size || 24; onModified: root.set("font_size", value) }
            Ui.Button { focusable: true; width: parent.width; text: root.showAppearance ? "▾ Caption window appearance" : "▸ Caption window appearance"; bordered: true; onClicked: root.showAppearance = !root.showAppearance }
            Column {
              width: parent.width; visible: root.showAppearance; spacing: Style.spacing.md
              Note { text: "Only the caption window is affected. −1 uses the Omarchy theme default. Lower the transparency so the backdrop behind black or white text shows." }
              Ui.NumberField { label: "Background transparency (%)"; from: -1; to: 100; value: root.config.background_transparency === undefined ? -1 : root.config.background_transparency; onModified: root.set("background_transparency", value) }
              Ui.NumberField { label: "Border thickness (px)"; from: -1; to: 16; value: root.config.border_width === undefined ? -1 : root.config.border_width; onModified: root.set("border_width", value) }
              Ui.NumberField { label: "Retained caption paragraphs"; from: 50; to: 5000; value: root.config.history_lines || 500; onModified: root.set("history_lines", value) }
            }
            Note { text: root.sessionState.shortcuts === false ? "Shortcut actions are not installed yet, so Launch & Bind cannot list Start, Stop and the other actions." : "Shortcuts: Launch & Bind → Apps → Video Trans → Shortcuts, or run video-trans help in a terminal." }
            Ui.Button { focusable: true; width: parent.width; visible: root.sessionState.shortcuts === false; bordered: true; selected: true; enabled: !root.busy; text: "Add shortcut actions"; tooltipText: "Installs the video-trans command and the Video Trans desktop entry with its actions"; onClicked: root.request({action: "install-shortcuts"}) }
          }
          Note { text: "Settings save immediately. Closing this popup leaves captions running; ■ Stop ends them and frees the models."; opacity: 0.65 }
        }

        Column {
          width: parent.width
          spacing: Style.spacing.md
          visible: root.showProvider && !root.showManualView
          Ui.Button { focusable: true; width: parent.width; text: "← Back to Caption Controls · ⌫"; bordered: true; onClicked: root.showProvider = false }
          Text { text: "Translation provider"; color: Theme.Color.accent; font.family: Style.font.family; font.pixelSize: Style.font.body; font.bold: true }
          Ui.Dropdown { id: providerPicker2; width: parent.width; label: "Translator"; options: [{value: "llama.cpp", label: "llama.cpp · local"}, {value: "Ollama", label: "Ollama · local"}, {value: "Online", label: "Online · OpenAI-compatible server"}]; value: root.config.provider || "llama.cpp"; enabled: !root.locked; onChanged: { root.selectProvider(value); providerPicker2.value = Qt.binding(function() { return root.config.provider || "llama.cpp" }) } }
          Note { text: root.config.provider === "Online" ? "Recognized text is sent to this server, which may charge for use. Audio never leaves this computer. Use HTTPS for remote servers." : "Local translation: recognized text stays on this computer. Video Trans starts the " + (root.config.provider === "Ollama" ? "Ollama" : "llama.cpp") + " user service on Start and stops it afterwards if it started it." }
          Column {
            width: parent.width; spacing: Style.spacing.md; enabled: !root.locked
            Ui.PanelSectionHeader { text: "Server address" }
            Ui.TextField { pasteHandler: root.pasteInto; width: parent.width; text: root.config.endpoint || ""; placeholderText: "Base URL, e.g. https://api.openai.com/v1"; onEditingFinished: if (text !== (root.config.endpoint || "")) root.set("endpoint", text) }
            Ui.PanelSectionHeader { text: "Model ID" }
            Ui.TextField { pasteHandler: root.pasteInto; width: parent.width; text: root.config.model || ""; placeholderText: "e.g. gpt-4o-mini"; onEditingFinished: if (text !== (root.config.model || "")) root.set("model", text) }
            Ui.PanelSectionHeader { text: "API key or bearer token" }
            Ui.TextField { id: token; pasteHandler: root.pasteInto; width: parent.width; password: true; placeholderText: root.sessionState.key_ready ? "Token configured · type to replace" : "Paste with Ctrl+V" }
            Ui.Toggle { id: remember; width: parent.width; label: "Save token on this device (owner-only file)"; checked: root.sessionState.remember_token === true; onClicked: { var desired = !checked; var next = Object.assign({}, root.sessionState); next.remember_token = desired; root.sessionState = next; root.request({action: "configure", remember_token: desired}) } }
            Ui.Button { focusable: true; text: "Apply token"; bordered: true; selected: enabled; enabled: token.text.length > 0; onClicked: { root.request({action: "configure", token: token.text, remember_token: remember.checked}); token.text = "" } }
          }
          Note { text: root.stepNote("provider", "Provider ready.") + (root.stepFor("model") && !root.stepFor("model").ok ? "\n" + root.stepFor("model").problem : "") }
          Ui.Button { focusable: true; width: parent.width; text: "← Back to Caption Controls · ⌫"; bordered: true; onClicked: root.showProvider = false }
        }

        Column {
          width: parent.width
          spacing: Style.space(10)
          visible: root.showManualView
          Ui.Button { width: parent.width; text: "← Back to Caption Controls · ⌫"; bordered: true; focusable: true; onClicked: root.showManualView = false }
          Repeater {
            model: [
              {
                "title": "1. First Session",
                "body": "• Open the popup: the Not ready yet card names the one next step and a button that does it. Follow it until ✓ Ready appears.\n• Set up now installs missing system packages (you confirm a password prompt) and the private Python runtime.\n• Then choose the playback device to caption, download the Whisper model once, and let Choose a model automatically pick a translation model.\n• Other options in the card offer alternatives, e.g. the microphone, a smaller Whisper model or another translator."
              },
              {
                "title": "2. Start, Stop & Captions",
                "body": "• ▶ Start begins capture and opens the caption window; ■ Stop ends it and frees the models.\n• Captions opens the caption window without capturing; Clear captions removes its text.\n• The bar icon is green while captions run; right-click it to start or stop.\n• Closing this popup leaves captions running.\n• If Start fails, the startup check lists what is missing."
              },
              {
                "title": "3. Listening",
                "body": "• Audio output captions what you hear (video, calls); Microphone captions speech in the room.\n• Device chooses which output or microphone is captured.\n• Whisper models: small is a good default; tiny/base are faster, medium/large more accurate. Each downloads once.\n• Recognition options: keep Spoken language on Detect automatically unless detection guesses wrong."
              },
              {
                "title": "4. Translation",
                "body": "• Translate into chooses the caption language.\n• llama.cpp and Ollama translate on this computer and start on demand. Online sends recognized text to your server.\n• Choose automatically picks an installed model by name for the target language; it is a heuristic, not a benchmark.\n• Provider settings… holds the server address, model ID and API key. Paste with Ctrl+V. Saving the token is optional."
              },
              {
                "title": "5. Caption Window",
                "body": "• Left-drag moves it; the bottom-right handle (shown while the pointer is over it) resizes it. Shift + drag selects text.\n• Caption text colour: Automatic (default) measures the video just above the captions every 2 s and picks white or black; or choose the theme, white, yellow, cyan, green, orange, pink, blue or black. The backdrop adapts for contrast. Next caption text colour cycles through them.\n• Scroll for older captions; turn off Follow new captions to stop automatic scrolling.\n• Captions group: display duration, font size and window appearance (−1 uses the theme default).\n• The window stays above fullscreen video on the workspace where it opened."
              },
              {
                "title": "6. Shortcuts",
                "body": "• Launch & Bind → Apps → Video Trans → Shortcuts binds Start / stop, Start, Stop, Show, Clear, Follow, caption text colour, larger / smaller text, input and model actions.\n• The Video Trans tray menu (Launch & Bind → Plugins → Running in the bar) offers the same entries plus target language and input.\n• Terminal: video-trans toggle | start | stop | show | clear | target French | status. video-trans help lists all."
              },
              {
                "title": "7. Troubleshooting & Privacy",
                "body": "• No captions: check the device in Listening and the startup check.\n• Wrong language: set Spoken language in Recognition options, or use a larger Whisper model.\n• Slow captions: use a smaller Whisper or translation model.\n• Audio stays local; only recognized text goes to the translator you chose.\n• Saved tokens are owner-only plaintext under ~/.config/video-trans."
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
                Text { width: parent.width; text: modelData.title; textFormat: Text.PlainText; color: Theme.Color.accent; font.family: Style.font.family; font.pixelSize: Theme.Style.font.bodySmall; font.bold: true; wrapMode: Text.Wrap }
                Text { width: parent.width; text: modelData.body; textFormat: Text.PlainText; color: Color.foreground; opacity: 0.85; font.family: Style.font.family; font.pixelSize: Style.font.caption; wrapMode: Text.Wrap }
              }
            }
          }
          Ui.Button { width: parent.width; text: "← Back to Caption Controls · ⌫"; bordered: true; focusable: true; onClicked: root.showManualView = false }
        }
      }
    }
  }
}
