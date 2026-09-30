"""Video Trans: a resizable, persistent caption window and provider settings."""
import json
import os
from pathlib import Path
import signal
import sys

from PySide6.QtCore import QEvent, QProcess, QTimer, Qt
from PySide6.QtGui import QFont, QPalette, QColor, QPainter, QPen
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox,
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QScrollArea,
    QPushButton, QSpinBox, QTabWidget, QTextEdit, QVBoxLayout, QWidget)

from core import CONFIG, LANGUAGES, load_settings, save_json, read_theme


class ResizeGrip(QWidget):
    """Always visible grip using compositor-native resizing on Wayland."""
    def __init__(self, parent):
        super().__init__(parent)
        self.setFixedSize(28, 28)
        self.setCursor(Qt.SizeFDiagCursor)
        self.setToolTip('Drag to resize captions')

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setPen(QPen(self.palette().color(QPalette.WindowText), 2))
        for offset in (7, 13, 19):
            painter.drawLine(26 - offset, 24, 24, 26 - offset)

    def mousePressEvent(self, event):
        handle = self.window().windowHandle()
        if event.button() == Qt.LeftButton and handle is not None:
            if handle.startSystemResize(Qt.RightEdge | Qt.BottomEdge):
                event.accept()
                return
        super().mousePressEvent(event)


class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Video Trans — Live captions')
        self.border_focused = True
        self.resize(900, 460)
        self.setMinimumSize(430, 230)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.settings = load_settings()
        self.resize(int(self.settings.get('width', 900)), int(self.settings.get('height', 460)))
        self.closing = False
        self.running = False
        self.starting = False
        self.stopping = False
        self.last_error = ''
        self.models = []
        self.buffer = bytearray()
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.SeparateChannels)
        self.process.readyReadStandardOutput.connect(self.read_events)
        self.process.readyReadStandardError.connect(lambda: self.process.readAllStandardError())
        self.process.finished.connect(self.finished)
        self.process.errorOccurred.connect(self.worker_error)
        layout = QVBoxLayout()
        wrapper = QWidget()
        wrapper.setObjectName('videoTransSurface')
        wrapper.setLayout(layout)
        self.setCentralWidget(wrapper)
        buttons = QHBoxLayout()
        self.start = QPushButton('Start')
        self.start.clicked.connect(self.start_capture)
        self.stop = QPushButton('Stop / free models')
        self.stop.clicked.connect(self.stop_capture)
        self.stop.setEnabled(False)
        self.compact = QPushButton('Caption mode')
        self.compact.clicked.connect(self.toggle_compact)
        clear = QPushButton('Clear')
        clear.clicked.connect(lambda: self.captions.clear())
        self.scroll = QCheckBox('Follow new text')
        self.scroll.setChecked(self.settings['auto_scroll'])
        for item in (self.start, self.stop, self.compact, clear, self.scroll):
            buttons.addWidget(item)
        # Translation controls belong to the native Omarchy popup. The Qt
        # window contains only captions and a resize handle.
        self.start.hide()
        self.stop.hide()
        self.compact.hide()
        clear.hide()
        self.scroll.hide()
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        self.resize_grip = ResizeGrip(wrapper)
        layout.addWidget(self.resize_grip, 0, Qt.AlignRight)
        self.captions = QTextEdit()
        self.captions.setObjectName('videoTransCaptions')
        self.captions.setReadOnly(True)
        self.captions.setPlaceholderText('Select an audio input and a translation model in Settings, then press Start. Captions stay until you clear them.')
        self.captions.document().setMaximumBlockCount(int(self.settings['history_lines']))
        self.tabs.addTab(self.captions, 'Captions')
        self.settings_widget = QWidget()
        self.form = QFormLayout(self.settings_widget)
        settings_scroll = QScrollArea()
        settings_scroll.setWidgetResizable(True)
        settings_scroll.setWidget(self.settings_widget)
        self.tabs.addTab(settings_scroll, 'Settings')
        self.tabs.setTabVisible(1, False)
        self.tabs.tabBar().hide()
        self.speech_provider = QComboBox()
        self.speech_provider.addItems(['Whisper (local)'])
        self.audio_input = QComboBox()
        self.audio_input.addItems(['Audio output', 'Microphone'])
        self.audio_input.setCurrentText(self.settings.get('audio_input', 'Audio output'))
        self.provider = QComboBox()
        self.provider.addItems(['llama.cpp', 'Ollama', 'Online'])
        self.provider.setCurrentText(self.settings['provider'])
        self.endpoint = QLineEdit(self.settings['endpoint'])
        self.model = QComboBox()
        self.model.setEditable(True)
        self.model.setCurrentText(self.settings['model'])
        refresh = QPushButton('Start provider / refresh models')
        refresh.clicked.connect(self.refresh_models)
        suggest = QPushButton('Auto-select local model for target language')
        suggest.clicked.connect(self.auto_select)
        self.token = QLineEdit()
        self.token.setEchoMode(QLineEdit.Password)
        self.token.setPlaceholderText('API key or bearer access token')
        self.remember = QCheckBox('Save token locally (owner-only file)')
        try:
            tokens = json.loads((CONFIG / 'credentials.json').read_text())
        except FileNotFoundError:
            tokens = {}
        self.tokens = tokens
        self.load_token()
        self.target = QComboBox()
        self.target.setEditable(True)
        self.target.addItems(LANGUAGES)
        self.target.setCurrentText(self.settings['target'])
        self.source = QComboBox()
        self.source.setEditable(True)
        self.source.addItems(['auto', 'en', 'de', 'fr', 'es', 'it', 'ja', 'zh', 'ko', 'ru', 'ar'])
        self.source.setCurrentText(self.settings['source'])
        self.output = QComboBox()
        outputs_button = QPushButton('Refresh audio devices')
        outputs_button.clicked.connect(lambda: self.send('outputs'))
        self.speech_model = QComboBox()
        self.speech_model.setEditable(True)
        self.speech_model.addItems(['tiny', 'base', 'small', 'medium', 'large-v3', 'turbo'])
        self.speech_model.setCurrentText(self.settings['speech_model'])
        self.noise = QCheckBox('Suppress noise + speech-band filter; speech detection always enabled')
        self.noise.setChecked(self.settings['noise_filter'])
        self.chunk = QSpinBox()
        self.chunk.setRange(3, 15)
        self.chunk.setValue(self.settings['chunk_seconds'])
        self.chunk.setSuffix(' seconds')
        self.font_size = QSpinBox()
        self.font_size.setRange(12, 64)
        self.font_size.setValue(self.settings['font_size'])
        self.transparency = QSpinBox()
        self.transparency.setRange(-1, 100)
        self.transparency.setSpecialValueText('Omarchy theme default')
        self.transparency.setValue(self.settings.get('background_transparency', -1))
        self.transparency.setSuffix('% transparent')
        self.border_width = QSpinBox()
        self.border_width.setRange(-1, 16)
        self.border_width.setSpecialValueText('Omarchy theme default')
        self.border_width.setValue(self.settings.get('border_width', -1))
        self.border_width.setSuffix(' px')
        self.history = QSpinBox()
        self.history.setRange(50, 5000)
        self.history.setValue(self.settings['history_lines'])
        for label, widget in [('Speech provider', self.speech_provider), ('Audio input type', self.audio_input),
                              ('Audio input device', self.output), ('', outputs_button),
                              ('Translation provider', self.provider), ('Endpoint (base URL or /v1)', self.endpoint),
                              ('API key / bearer authentication', self.token), ('', self.remember),
                              ('Translation model', self.model), ('', refresh), ('Target language', self.target), ('', suggest),
                              ('Source language (auto detects)', self.source), ('Whisper model', self.speech_model),
                              ('Noise filtering', self.noise), ('Audio chunk size', self.chunk),
                              ('Caption font size', self.font_size), ('Background transparency', self.transparency),
                              ('Border thickness', self.border_width),
                              ('Retained caption paragraphs', self.history)]:
            self.form.addRow(label, widget)
        hint = QLabel('Local: recognized text goes to llama.cpp / Ollama. Online: recognized text is sent to your endpoint.\n'
                      'Authentication accepts API keys or existing bearer tokens; browser OAuth login is not included.\n'
                      'Captions never expire. Scroll back or disable Follow to read at your own pace.')
        hint.setWordWrap(True)
        self.form.addRow(hint)
        self.status = QLabel('Ready · select Audio output or Microphone explicitly')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.status.hide()
        self.provider.currentTextChanged.connect(self.provider_changed)
        self.audio_input.currentTextChanged.connect(lambda _: self.send('outputs'))
        self.endpoint.editingFinished.connect(self.load_token)
        self.font_size.valueChanged.connect(self.apply_appearance)
        self.transparency.valueChanged.connect(self.apply_appearance)
        self.border_width.valueChanged.connect(self.apply_appearance)
        self.apply_appearance()
        self.theme_timer = QTimer(self)
        self.theme_timer.timeout.connect(self.apply_appearance)
        self.theme_timer.start(2000)
        self.send('outputs')

    def set_status(self, text):
        self.status.setText(text)
        self.captions.setPlaceholderText(text)

    def showEvent(self, event):
        super().showEvent(event)
        self.border_focused = True
        self.apply_appearance()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.ActivationChange and hasattr(self, 'border_width'):
            self.border_focused = self.isActiveWindow()
            self.apply_appearance()

    def apply_appearance(self):
        self.captions.setFont(QFont('sans-serif', self.font_size.value()))
        theme = read_theme()
        background = QColor(theme['background'])
        foreground = QColor(theme['foreground'])
        accent = QColor(theme['accent'])
        palette = self.palette()
        for role, color in ((QPalette.Window, background), (QPalette.Base, background), (QPalette.Button, background.lighter(140)),
                            (QPalette.WindowText, foreground), (QPalette.Text, foreground), (QPalette.ButtonText, foreground),
                            (QPalette.Highlight, accent), (QPalette.HighlightedText, background)):
            palette.setColor(role, color)
        self.setPalette(palette)
        transparency = self.transparency.value()
        if transparency < 0:
            transparency = theme['background_transparency']
        width = self.border_width.value()
        if width < 0:
            width = theme['border_width']
        alpha = round(255 * (100 - transparency) / 100)
        border_color = theme['border_color'] if self.border_focused else 'transparent'
        self.centralWidget().setStyleSheet(
            f'QWidget#videoTransSurface {{ background: rgba({background.red()}, {background.green()}, {background.blue()}, {alpha}); '
            f'border: {width}px solid {border_color}; }} '
            f'QTextEdit#videoTransCaptions {{ background: transparent; color: {foreground.name()}; border: none; padding: 12px; }} '
            'QWidget#videoTransSurface > QWidget { background: transparent; } '
            f'QLabel, QCheckBox {{ color: {foreground.name()}; }} '
            'QTabWidget::pane { background: transparent; border: none; }')
        self.captions.viewport().setAutoFillBackground(False)

    def token_id(self):
        return self.provider.currentText() + ' ' + self.endpoint.text().strip().rstrip('/')

    def load_token(self):
        value = self.tokens.get(self.token_id(), '')
        self.token.setText(value)
        self.remember.setChecked(bool(value))

    def provider_changed(self, name):
        self.endpoint.setText({'llama.cpp': 'http://127.0.0.1:8080', 'Ollama': 'http://127.0.0.1:11434',
                               'Online': 'https://api.openai.com/v1'}[name])
        self.model.clear()
        self.load_token()

    def current_settings(self):
        return dict(provider=self.provider.currentText(), endpoint=self.endpoint.text().strip(),
                    speech_provider=self.speech_provider.currentText(), audio_input=self.audio_input.currentText(),
                    model=self.model.currentText().strip(), target=self.target.currentText().strip(),
                    source=self.source.currentText().strip(), speech_model=self.speech_model.currentText().strip(),
                    chunk_seconds=self.chunk.value(), noise_filter=self.noise.isChecked(),
                    font_size=self.font_size.value(), background_transparency=self.transparency.value(),
                    border_width=self.border_width.value(), history_lines=self.history.value(),
                    output=self.output.currentData() or '', auto_scroll=self.scroll.isChecked())

    def save(self):
        self.settings = self.current_settings()
        self.settings.update(width=self.width(), height=self.height())
        save_json(CONFIG / 'settings.json', self.settings)
        if self.remember.isChecked() and self.token.text():
            self.tokens[self.token_id()] = self.token.text()
        else:
            self.tokens.pop(self.token_id(), None)
        save_json(CONFIG / 'credentials.json', self.tokens)

    def send(self, action):
        if self.stopping:
            return False
        if action in ('start', 'models', 'suggest'):
            self.last_error = ''
        if self.process.state() == QProcess.NotRunning:
            self.buffer.clear()
            self.process.start(sys.executable, ['-u', str(Path(__file__).with_name('backend.py'))])
            if not self.process.waitForStarted(3000):
                self.set_status('Worker failed to start. Run setup.sh.')
                return False
        data = dict(action=action, settings=self.current_settings(), token=self.token.text())
        self.process.write((json.dumps(data) + '\n').encode())
        return True

    def worker_error(self, error):
        if error == QProcess.FailedToStart:
            self.running = self.starting = False
            self.start.setEnabled(True)
            self.stop.setEnabled(False)
            self.settings_widget.setEnabled(True)
            self.set_status('Worker failed to start. Run setup.sh.')

    def refresh_models(self):
        self.save()
        self.set_status('Starting provider and discovering models…')
        self.stop.setEnabled(True)
        self.send('models')

    def auto_select(self):
        self.save()
        self.set_status('Discovering local models and choosing a suggestion for the target language…')
        self.stop.setEnabled(True)
        self.send('suggest')

    def start_capture(self):
        if self.running or self.stopping:
            return
        if not self.output.currentData() or not self.model.currentText().strip():
            self.set_status('Select an audio input device and translation model first.')
            return
        self.save()
        self.captions.document().setMaximumBlockCount(self.history.value())
        self.running = True
        self.starting = True
        self.set_status('Starting translation · loading Whisper and connecting to the provider…')
        self.start.setEnabled(False)
        self.stop.setEnabled(True)
        self.settings_widget.setEnabled(False)
        self.tabs.setCurrentIndex(0)
        if self.send('start') is False:
            self.worker_error(QProcess.FailedToStart)

    def stop_capture(self):
        if self.process.state() != QProcess.NotRunning:
            self.set_status('Stopping capture and releasing models…')
            self.process.write(b'{"action":"stop"}\n')
            self.stopping = True
            self.start.setEnabled(False)
            self.stop.setEnabled(False)

    def toggle_compact(self):
        compact = self.tabs.isTabVisible(1)
        self.tabs.setTabVisible(1, not compact)
        self.tabs.tabBar().setVisible(not compact)
        self.tabs.setCurrentIndex(0)
        self.compact.setText('Settings' if compact else 'Caption mode')

    def read_events(self):
        self.buffer.extend(bytes(self.process.readAllStandardOutput()))
        while b'\n' in self.buffer:
            line, _, remainder = self.buffer.partition(b'\n')
            self.buffer = bytearray(remainder)
            try:
                event = json.loads(line)
            except ValueError:
                continue
            kind = event.get('type')
            if kind == 'started':
                self.starting = False
                self.set_status('Listening · waiting for speech from the selected audio device…')
            elif kind in ('error', 'status'):
                self.set_status(event['message'])
                if kind == 'error':
                    self.last_error = event['message']
            elif kind == 'outputs':
                selected = self.output.currentData() or self.settings.get('output')
                self.output.clear()
                for output in event['outputs']:
                    self.output.addItem(output['label'], output['name'])
                index = self.output.findData(selected)
                if index >= 0:
                    self.output.setCurrentIndex(index)
            elif kind == 'models':
                self.models = event['models']
                selected = self.model.currentText()
                self.model.clear()
                self.model.addItems(event['models'])
                if selected:
                    self.model.setCurrentText(selected)
            elif kind == 'suggestion':
                self.models = event['models']
                self.provider.setCurrentText(event['provider'])
                self.endpoint.setText(event['endpoint'])
                self.load_token()
                self.model.clear()
                self.model.addItems(event['models'])
                self.model.setCurrentText(event['model'])
                self.set_status(event['reason'])
                self.save()
            elif kind == 'caption':
                scroll = self.captions.verticalScrollBar()
                position = scroll.value()
                self.captions.append('')
                cursor = self.captions.textCursor()
                cursor.movePosition(cursor.MoveOperation.End)
                cursor.insertText(event['timestamp'] + ' · ' + event['language'] + '\n' + event['text'])
                if self.scroll.isChecked():
                    scroll.setValue(scroll.maximum())
                else:
                    scroll.setValue(position)
                self.set_status('Listening · detected ' + event['language'] + ' → ' + self.target.currentText())

    def finished(self, code, status):
        self.running = False
        self.starting = False
        self.stopping = False
        self.start.setEnabled(True)
        self.stop.setEnabled(False)
        self.settings_widget.setEnabled(True)
        if self.closing:
            self.close()
            QApplication.instance().quit()
        elif code != 0:
            self.set_status('Worker exited unexpectedly. Check provider configuration and restart.')
        elif self.last_error:
            self.set_status(self.last_error + ' · worker stopped')
        else:
            self.set_status('Stopped · speech worker exited; captions retained')

    def closeEvent(self, event):
        self.closing = True
        self.save()
        if self.process.state() != QProcess.NotRunning:
            self.closing = True
            self.hide()
            self.stop_capture()
            event.ignore()
        else:
            event.accept()
            if self.closing:
                QApplication.instance().quit()

    def snapshot(self):
        return dict(settings=self.current_settings(), models=self.models,
                    outputs=[dict(name=self.output.itemData(i), label=self.output.itemText(i)) for i in range(self.output.count())],
                    running=self.running, starting=self.starting, stopping=self.stopping, overlay=self.isVisible(),
                    key_ready=bool(self.token.text()), remember_token=self.remember.isChecked(),
                    status=self.status.text())

    def configure(self, request):
        values = request.get('settings', {})
        if not isinstance(values, dict):
            raise ValueError('Settings must be an object')
        if self.running:
            values = {key: value for key, value in values.items() if key in
                      ('font_size', 'background_transparency', 'border_width', 'history_lines', 'auto_scroll')}
        for key, field in [('provider', self.provider), ('audio_input', self.audio_input),
                           ('model', self.model), ('target', self.target), ('source', self.source), ('speech_model', self.speech_model)]:
            if key in values:
                field.setCurrentText(str(values[key]))
        if 'endpoint' in values:
            endpoint = str(values['endpoint'])
            if endpoint != self.endpoint.text():
                self.endpoint.setText(endpoint)
                self.load_token()
        # provider/endpoint changes clear the model, so restore it last.
        if 'model' in values:
            self.model.setCurrentText(str(values['model']))
        if 'output' in values:
            value = str(values['output'])
            index = self.output.findData(value)
            if index < 0 and value:
                self.output.addItem(value, value)
                index = self.output.findData(value)
            self.output.setCurrentIndex(index)
        for key, field in [('chunk_seconds', self.chunk), ('font_size', self.font_size),
                           ('background_transparency', self.transparency), ('border_width', self.border_width),
                           ('history_lines', self.history)]:
            if key in values:
                field.setValue(int(values[key]))
        if 'noise_filter' in values:
            self.noise.setChecked(bool(values['noise_filter']))
        if 'auto_scroll' in values:
            self.scroll.setChecked(bool(values['auto_scroll']))
        if 'token' in request:
            self.token.setText(str(request['token']))
        if 'remember_token' in request:
            self.remember.setChecked(bool(request['remember_token']))
        self.captions.document().setMaximumBlockCount(self.history.value())
        self.save()
        self.apply_appearance()

    def handle_request(self, request):
        action = request.get('action', 'state')
        if action == 'configure':
            self.configure(request)
        elif action == 'start':
            self.show()
            self.start_capture()
        elif action == 'stop':
            self.close()
        elif action == 'models':
            self.refresh_models()
        elif action == 'suggest':
            self.auto_select()
        elif action == 'outputs':
            self.send('outputs')
        elif action == 'show':
            self.show()
            self.raise_()
            self.activateWindow()
        elif action == 'clear':
            self.captions.clear()
        elif action == 'close' or (action == 'release' and not self.isVisible()):
            self.closing = True
            self.close()
        return self.snapshot()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName('Video Trans')
    app.setDesktopFileName('video-trans')
    app.setQuitOnLastWindowClosed(False)
    palette = QPalette()
    for role, color in ((QPalette.Window, '#20232b'), (QPalette.WindowText, '#e8eaf0'),
                        (QPalette.Base, '#15171c'), (QPalette.AlternateBase, '#292e38'),
                        (QPalette.Text, '#e8eaf0'), (QPalette.Button, '#303641'),
                        (QPalette.ButtonText, '#e8eaf0'), (QPalette.Highlight, '#336d79'),
                        (QPalette.HighlightedText, '#ffffff'), (QPalette.PlaceholderText, '#9097a5')):
        palette.setColor(role, QColor(color))
    app.setStyle('Fusion')
    app.setPalette(palette)
    # Per-user local socket: activating twice raises the existing window.
    from bridge import socket_path
    name = socket_path()
    socket = QLocalSocket()
    socket.connectToServer(name)
    if socket.waitForConnected(300):
        socket.write(b'{"action":"state"}\n' if '--controller' in sys.argv else b'{"action":"show"}\n')
        socket.waitForBytesWritten(300)
        return 0
    QLocalServer.removeServer(name)
    server = QLocalServer()
    server.setSocketOptions(QLocalServer.UserAccessOption)
    if not server.listen(name):
        raise RuntimeError('Could not create Video Trans activation socket')
    window = Window()
    connections = set()
    def activate():
        connection = server.nextPendingConnection()
        if not connection:
            return
        connections.add(connection)
        data = bytearray()
        def receive():
            data.extend(bytes(connection.readAll()))
            if len(data) > 65536:
                connection.disconnectFromServer()
                return
            if b'\n' not in data:
                return
            try:
                request = json.loads(bytes(data).split(b'\n', 1)[0])
                response = window.handle_request(request)
            except (ValueError, TypeError, AttributeError) as exc:
                response = dict(error=str(exc))
            connection.write((json.dumps(response) + '\n').encode())
            connection.flush()
            connection.disconnectFromServer()
        connection.readyRead.connect(receive)
        connection.disconnected.connect(lambda: connections.discard(connection))
        connection.disconnected.connect(connection.deleteLater)
        receive()
    server.newConnection.connect(activate)
    signal.signal(signal.SIGTERM, lambda *_: window.close())
    signal.signal(signal.SIGINT, lambda *_: window.close())
    timer = QTimer()
    timer.timeout.connect(lambda: None)
    timer.start(200)
    if '--controller' not in sys.argv:
        window.show()
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
