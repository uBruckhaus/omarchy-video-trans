"""Video Trans tray icon: always present while the bar widget is, like Screen Narrator's.

Launch & Bind lists it under Plugins → Running in the bar, where every entry can be
clicked or bound to a key. Entries run `bridge.sh <action>` (the `video-trans`
command), which starts the caption controller only when an action needs it. The
icon and checkmarks follow the controller over its socket; while it is off they
come from the settings file. Labels stay fixed in every state because shortcuts
bind entries by label, and entries stay enabled because disabled ones are skipped.
"""
import json
import os
from pathlib import Path
import re
import sys

from PySide6.QtCore import QLockFile, QProcess, QTimer, Qt
from PySide6.QtGui import QActionGroup, QColor, QFont, QIcon, QPainter, QPen, QPixmap
from PySide6.QtNetwork import QLocalSocket
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from bridge import socket_path
from core import LANGUAGES, load_settings

ROOT = Path(__file__).resolve().parent
INPUTS = ['Audio output', 'Microphone']


def plain(text, limit=300):
    """Notification daemons and tray hosts render markup: drop <, >, & and control characters."""
    return ''.join(c for c in str(text) if c >= ' ' and c not in '<>&\x7f')[:limit]


def theme_green():
    state = Path(os.environ.get('XDG_STATE_HOME', Path.home() / '.local/state'))
    try:
        text = (state / 'omarchy/current/theme/colors.toml').read_text()
    except OSError:
        return '#66c98b'
    match = re.search(r'^\s*green\s*=\s*"(#[0-9a-fA-F]{6})"', text, re.M)
    return match.group(1) if match else '#66c98b'


class Tray(QSystemTrayIcon):
    def __init__(self):
        super().__init__()
        self.state = {}
        self.running = False
        self.jobs = set()
        self.buffer = bytearray()
        self.icons = {}
        menu = self.menu = QMenu()
        menu.addAction('Start / stop captions', lambda: self.run('toggle'))
        menu.addAction('Start captions', lambda: self.run('start'))
        menu.addAction('Stop captions', lambda: self.run('stop'))
        self.status_action = menu.addAction('Status: Off')
        self.status_action.setEnabled(False)
        menu.addSeparator()
        menu.addAction('Show captions', lambda: self.run('show'))
        menu.addAction('Clear captions', lambda: self.run('clear'))
        self.follow_action = menu.addAction('Follow new captions')
        self.follow_action.setCheckable(True)
        self.follow_action.triggered.connect(lambda checked: self.run('follow', 'on' if checked else 'off'))
        self.color_actions = self.choices('Caption text', ['Omarchy theme', 'White', 'Black'], 'text-color')
        menu.addAction('Larger caption text', lambda: self.run('font', 'bigger'))
        menu.addAction('Smaller caption text', lambda: self.run('font', 'smaller'))
        menu.addSeparator()
        self.target_actions = self.choices('Translate to', LANGUAGES, 'target')
        self.input_actions = self.choices('Audio input', INPUTS, 'input')
        menu.addSeparator()
        menu.addAction('Download Whisper model', lambda: self.run('download'))
        menu.addAction('Auto-select local model', lambda: self.run('suggest'))
        menu.addAction('Refresh models', lambda: self.run('models'))
        menu.addAction('Settings…', lambda: self.run('settings'))
        menu.aboutToShow.connect(self.refresh)
        self.setContextMenu(menu)
        self.activated.connect(self.clicked)
        self.socket = QLocalSocket(self)
        self.socket.connected.connect(self.ask)
        self.socket.readyRead.connect(self.receive)
        self.socket.disconnected.connect(self.disconnected)
        self.socket.errorOccurred.connect(lambda *_: self.disconnected())
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(2000)
        self.poll()

    def choices(self, title, values, command):
        menu = self.menu.addMenu(title)
        group = QActionGroup(menu)
        actions = {}
        for value in values:
            action = menu.addAction(value)
            action.setCheckable(True)
            group.addAction(action)
            argument = {'Omarchy theme': 'theme', 'White': 'white', 'Black': 'black'}.get(value, value) if command == 'text-color' else value
            action.triggered.connect(lambda checked=False, v=argument: self.run(command, v))
            actions[value] = action
        return actions

    def icon(self, running):
        """A caption badge: outlined while off, filled in the theme's green while translating."""
        color = theme_green() if running else '#c8ccd4'
        if color not in self.icons:
            pixmap = QPixmap(64, 64)
            pixmap.fill(Qt.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setPen(QPen(QColor(color), 5))
            if running:
                painter.setBrush(QColor(color))
            painter.drawRoundedRect(5, 12, 54, 40, 9, 9)
            painter.setPen(QColor('#15171c') if running else QColor(color))
            font = QFont('sans-serif')
            font.setPixelSize(24)
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(pixmap.rect(), Qt.AlignCenter, 'CC')
            painter.end()
            self.icons[color] = QIcon(pixmap)
        return self.icons[color]

    def run(self, command, value=None):
        """Run one `video-trans` action without blocking the menu; report failures."""
        job = QProcess(self)
        job.setProcessChannelMode(QProcess.SeparateChannels)
        job.finished.connect(lambda code, _status, j=job: self.finished(j, code))
        self.jobs.add(job)
        job.start('bash', [str(ROOT / 'bridge.sh'), command] + ([value] if value else []))

    def finished(self, job, code):
        self.jobs.discard(job)
        if code:
            message = bytes(job.readAllStandardError()).decode('utf-8', 'replace').strip()
            self.showMessage('Video Trans', plain(message[-300:]) or 'The action failed.', QSystemTrayIcon.Warning, 6000)
        job.deleteLater()
        self.poll()

    def clicked(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.run('settings')
        elif reason == QSystemTrayIcon.ActivationReason.MiddleClick:
            self.run('toggle')

    def poll(self):
        if self.socket.state() == QLocalSocket.ConnectedState:
            self.ask()
        elif self.socket.state() == QLocalSocket.UnconnectedState:
            if os.path.exists(socket_path()):
                self.socket.connectToServer(socket_path())
            else:
                self.disconnected()

    def ask(self):
        self.socket.write(b'{"action":"state","keep":true}\n')
        self.socket.flush()

    def receive(self):
        self.buffer.extend(bytes(self.socket.readAll()))
        while b'\n' in self.buffer:
            line, _, rest = bytes(self.buffer).partition(b'\n')
            self.buffer[:] = rest
            try:
                self.state = json.loads(line)
            except ValueError:
                continue
        if len(self.buffer) > 1024 * 1024:
            self.socket.abort()
        self.refresh()

    def disconnected(self):
        self.buffer.clear()
        self.state = {}
        self.refresh()

    def refresh(self):
        state = self.state
        self.running = state.get('running') is True or state.get('starting') is True
        try:
            settings = state.get('settings') or load_settings()
        except (OSError, ValueError):
            settings = {}
        status = plain(state.get('status') or 'Off', 120)
        self.status_action.setText('Status: ' + (status[:77] + '…' if len(status) > 78 else status))
        self.setIcon(self.icon(self.running))
        self.setToolTip('Video Trans — ' + ('translating → ' + plain(settings.get('target', ''), 40) if self.running else status))
        self.follow_action.setChecked(settings.get('auto_scroll', True) is not False)
        color = {'white': 'White', 'black': 'Black'}.get(settings.get('text_color'), 'Omarchy theme')
        for actions, current in ((self.target_actions, settings.get('target')), (self.input_actions, settings.get('audio_input')),
                                 (self.color_actions, color)):
            for value, action in actions.items():
                action.setChecked(value == current)


def main():
    app = QApplication(sys.argv)
    # Match the desktop ID so Launch & Bind names the tray entry Video Trans.
    app.setApplicationName('video-trans')
    app.setApplicationDisplayName('Video Trans')
    app.setQuitOnLastWindowClosed(False)
    runtime = Path(os.environ.get('XDG_RUNTIME_DIR', '/tmp'))
    lock = QLockFile(str(runtime / f'video-trans-tray-{os.getuid()}.lock'))
    if not lock.tryLock(0):
        return 0  # Another bar instance (monitor) already shows it.
    if not QSystemTrayIcon.isSystemTrayAvailable():
        return 0
    tray = Tray()
    tray.show()
    import signal
    signal.signal(signal.SIGTERM, lambda *_: app.quit())
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    keepalive = QTimer()
    keepalive.timeout.connect(lambda: None)  # let Python handle signals
    keepalive.start(500)
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
