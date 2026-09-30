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


def main():
    try:
        payload = json.loads(sys.stdin.readline())
        try:
            result = request(payload)
        except (FileNotFoundError, ConnectionRefusedError):
            if payload.get('action') in ('state', 'release', 'stop', 'close'):
                result = offline_state()
            else:
                subprocess.Popen([sys.executable, str(Path(__file__).with_name('gui.py')), '--controller'],
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 start_new_session=True)
                deadline = time.monotonic() + 8
                while True:
                    try:
                        result = request(payload)
                        break
                    except (FileNotFoundError, ConnectionRefusedError):
                        if time.monotonic() > deadline:
                            raise RuntimeError('Caption controller did not start. Run setup.sh.')
                        time.sleep(0.1)
        print(json.dumps(result), flush=True)
    except Exception as exc:
        print(json.dumps(dict(error='Video Trans: ' + str(exc))), flush=True)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
