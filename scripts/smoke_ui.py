"""Check native-panel IPC and independent overlay lifecycle with no inference."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bridge import request


def main():
    with tempfile.TemporaryDirectory() as directory:
        runtime = Path(directory) / 'runtime'
        runtime.mkdir(mode=0o700)
        os.environ.update(XDG_RUNTIME_DIR=str(runtime), XDG_CONFIG_HOME=directory,
                          QT_QPA_PLATFORM='offscreen', QT_QPA_PLATFORMTHEME='none')
        process = subprocess.Popen([sys.executable, str(Path(__file__).resolve().parents[1] / 'gui.py'), '--controller'],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            for _ in range(60):
                try:
                    state = request({'action': 'state'})
                    break
                except (FileNotFoundError, ConnectionRefusedError):
                    time.sleep(0.1)
            else:
                raise RuntimeError('Controller did not start')
            assert not state['overlay']
            state = request({'action': 'configure', 'settings': {'provider': 'Online',
                             'endpoint': 'https://example.invalid/v1', 'target': 'French'},
                             'token': 'synthetic-test-token', 'remember_token': False})
            assert state['settings']['target'] == 'French'
            assert state['key_ready'] and 'synthetic-test-token' not in str(state)
            state = request({'action': 'configure', 'settings': state['settings'] | {'background_transparency': 66, 'border_width': 6}})
            assert state['key_ready']
            assert state['settings']['background_transparency'] == 66
            assert request({'action': 'show'})['overlay']
            assert request({'action': 'release'})['overlay']
            assert process.poll() is None
            assert not request({'action': 'stop'})['overlay']
            process.wait(timeout=10)
            assert process.returncode == 0
            print('Native-panel IPC, private token handling, independent overlay and cleanup: OK')
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)


if __name__ == '__main__':
    main()
