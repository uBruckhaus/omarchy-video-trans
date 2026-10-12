"""Owner-only Unix socket bridge for native QML controls. Never prints tokens."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time


def socket_path():
    runtime = os.environ.get('XDG_RUNTIME_DIR', '/tmp')
    return str(Path(runtime) / ('video-trans-' + str(os.getuid()) + '.sock'))


def request(payload):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(4)
        client.connect(socket_path())
        client.sendall((json.dumps(payload) + '\n').encode())
        response = bytearray()
        while b'\n' not in response:
            data = client.recv(8192)
            if not data:
                raise RuntimeError('Caption controller disconnected')
            response.extend(data)
            if len(response) > 1024 * 1024:
                raise ValueError('Controller response too large')
        return json.loads(response.split(b'\n', 1)[0])


def offline_state():
    from core import load_settings, audio_devices, CONFIG
    settings = load_settings()
    try:
        outputs = audio_devices(settings['audio_input'])
        status = 'Ready'
    except Exception:
        outputs = []
        status = 'Audio device discovery unavailable'
    tokens = {}
    try:
        tokens = json.loads((CONFIG / 'credentials.json').read_text())
    except (OSError, ValueError):
        pass
    key = settings['provider'] + ' ' + settings['endpoint'].strip().rstrip('/')
    return dict(settings=settings, models=[], outputs=outputs, checks=[], running=False, starting=False, downloading=False, stopping=False,
                overlay=False, status=status, key_ready=bool(tokens.get(key)), remember_token=bool(tokens.get(key)))


def save_offline(values):
    """Settings changes while Video Trans is off go straight to the settings file."""
    from core import CONFIG, DEFAULTS, load_settings, save_json
    if not isinstance(values, dict):
        raise ValueError('Settings must be an object')
    settings = load_settings()
    for key, value in values.items():
        if key in DEFAULTS and key not in ('width', 'height'):
            settings[key] = type(DEFAULTS[key])(value)
    save_json(CONFIG / 'settings.json', settings)


def send(payload):
    """Send to the running controller; start it only for actions that need one."""
    import readiness
    action = payload.get('action')
    if action == 'paste':
        return readiness.read_clipboard()
    if action == 'setup':
        readiness.start_setup()
        return offline_state()
    if action == 'install-shortcuts':
        readiness.install_shortcuts()
        payload, action = dict(action='state'), 'state'
    try:
        return request(payload)
    except (FileNotFoundError, ConnectionRefusedError):
        if action in OFFLINE_ACTIONS:
            return offline_state()
        if action == 'configure' and set(payload) <= {'action', 'settings'}:
            save_offline(payload.get('settings', {}))
            return offline_state()
        if not readiness.runtime_ready():
            raise RuntimeError('Video Trans needs its one-time setup first. Press Set up now, or run video-trans setup.')
        subprocess.Popen([sys.executable, str(Path(__file__).with_name('gui.py')), '--controller'],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
        deadline = time.monotonic() + 8
        while True:
            try:
                return request(payload)
            except (FileNotFoundError, ConnectionRefusedError):
                if time.monotonic() > deadline:
                    raise RuntimeError('Caption controller did not start. Press Set up now in the Video Trans popup.')
                time.sleep(0.1)


# Nothing to stop, clear or cancel without a controller; never start one for these.
OFFLINE_ACTIONS = ('state', 'release', 'stop', 'close', 'clear', 'cancel-download', 'outputs')
# Command-line actions: the bar popup's buttons, desktop actions and tray entries.
COMMANDS = {
    'toggle': 'Start captions, or stop them when running',
    'start': 'Start captions and open the caption overlay',
    'stop': 'Stop captions and free models',
    'show': 'Show the caption overlay without capturing',
    'clear': 'Clear captions',
    'follow': 'Follow new captions: on, off or toggle (default)',
    'target': 'Translate into LANGUAGE, e.g. target German',
    'input': 'Capture "Audio output" or "Microphone"',
    'text-color': 'Caption text: white, black, theme, or toggle (black ↔ white)',
    'download': 'Download the selected Whisper model',
    'cancel-download': 'Cancel the Whisper download',
    'models': 'Start the provider and refresh its models',
    'suggest': 'Auto-select a local model for the target language',
    'settings': 'Open the Video Trans bar popup',
    'setup': 'Install missing packages, the private runtime and the shortcut entries',
    'status': 'Print the current state as JSON',
}
INPUTS = ('Audio output', 'Microphone')


def usage():
    width = max(map(len, COMMANDS))
    return 'usage: video-trans <action> [value]\n\n' + '\n'.join(
        f'  {name.ljust(width)}  {text}' for name, text in COMMANDS.items())


def change_setting(key, value):
    """Apply one setting to the running controller, or to the settings file when off."""
    result = send(dict(action='configure', settings={key: value}))
    if result.get('error') or result.get('settings', {}).get(key) == value:
        return result
    return dict(result, error='Video Trans: stop captions before changing ' +
                {'target': 'the target language', 'audio_input': 'the input'}.get(key, key))


def command(argv):
    """Run one command-line action and return the controller's answer."""
    name, value = argv[0], (argv[1] if len(argv) > 1 else '')
    if name not in COMMANDS or len(argv) > 2:
        raise ValueError(usage())
    if name == 'settings':
        subprocess.Popen(['omarchy-shell', 'shell', 'toggle', 'ubruckhaus.video-trans', '{}'],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
        return dict(status='Opened the Video Trans popup')
    if name == 'setup':
        import readiness
        readiness.run_setup(print)
        return dict(status='')
    if name == 'follow':
        if value not in ('', 'toggle', 'on', 'off'):
            raise ValueError('follow takes on, off or toggle')
        if value in ('', 'toggle'):
            current = send(dict(action='state')).get('settings', {}).get('auto_scroll', True)
            value = 'off' if current else 'on'
        return change_setting('auto_scroll', value == 'on')
    if name == 'text-color':
        if value not in ('', 'toggle', 'white', 'black', 'theme'):
            raise ValueError('text-color takes white, black, theme or toggle')
        if value in ('', 'toggle'):
            current = send(dict(action='state')).get('settings', {}).get('text_color', 'theme')
            value = 'white' if current == 'black' else 'black'
        return change_setting('text_color', value)
    if name == 'target':
        from core import LANGUAGES
        match = next((item for item in LANGUAGES if item.casefold() == value.strip().casefold()), None)
        if not match:
            raise ValueError('target takes one of: ' + ', '.join(LANGUAGES))
        return change_setting('target', match)
    if name == 'input':
        match = next((item for item in INPUTS if item.casefold() == value.strip().casefold()), None)
        if not match:
            raise ValueError('input takes "Audio output" or "Microphone"')
        return change_setting('audio_input', match)
    if value:
        raise ValueError(usage())
    result = send(dict(action='state' if name == 'status' else name))
    return with_steps(result) if name == 'status' else result


def with_steps(result):
    """Attach the setup steps and guided-setup progress the popup shows."""
    import readiness
    if 'settings' in result:
        result['steps'] = readiness.steps(result)
        result['setup'] = readiness.setup_status()
        result['shortcuts'] = readiness.shortcuts_installed()
    return result


def cli(argv):
    if argv[0] in ('help', '-h', '--help'):
        print(usage())
        return 0
    try:
        result = command(argv)
    except Exception as exc:
        print(str(exc) if isinstance(exc, ValueError) else 'Video Trans: ' + str(exc), file=sys.stderr)
        return 2 if isinstance(exc, ValueError) else 1
    if result.get('error'):
        print(result['error'], file=sys.stderr)
        return 1
    print(json.dumps(result) if argv[0] == 'status' else result.get('status', ''))
    return 0


def main():
    if len(sys.argv) > 1:
        return cli(sys.argv[1:])
    try:
        result = with_steps(send(json.loads(sys.stdin.readline())))
        print(json.dumps(result), flush=True)
    except Exception as exc:
        print(json.dumps(dict(error='Video Trans: ' + str(exc))), flush=True)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
