"""First-run readiness for the popup: the ordered setup steps, guided setup and bounded paste.

Standard library only, so the popup works before the private runtime exists. Every
check is local and quick (files, pactl, systemctl, loopback HTTP); remote endpoints
are never contacted here.
"""
import fcntl
import hashlib
import json
import os
import re
import selectors
import socket
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlparse

from core import save_json
import whisper_store

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share')) / 'video-trans'
RUNTIME_PYTHON = DATA / 'runtime/bin/python'
# Command → Arch package. Setup installs the missing ones through pkexec.
PACKAGES = {'ffmpeg': 'ffmpeg', 'pactl': 'libpulse', 'quickshell': 'quickshell', 'uv': 'uv'}
# Offered Whisper models (repository, size, pinned commit, file hashes): whisper_store.py.
WHISPER = whisper_store.MODELS
ENDPOINTS = {'llama.cpp': 'http://127.0.0.1:8080', 'Ollama': 'http://127.0.0.1:11434',
             'Online': 'https://api.openai.com/v1'}
PASTE_LIMIT = 8 * 1024
PASTE_TYPES = ('text/plain;charset=utf-8', 'text/plain', 'UTF8_STRING', 'TEXT', 'STRING')


def runtime_dir():
    return Path(os.environ.get('XDG_RUNTIME_DIR', '/tmp'))


def status_path():
    return runtime_dir() / f'video-trans-setup-{os.getuid()}.json'


def missing_packages():
    return [package for command, package in PACKAGES.items() if not shutil.which(command)]


def runtime_ready():
    """The runtime exists and was built from the current requirements.lock (setup.sh)."""
    if not (RUNTIME_PYTHON.is_file() and os.access(RUNTIME_PYTHON, os.X_OK)):
        return False
    try:
        record = (DATA / 'runtime/.verified-lock').read_text().strip()
        return record == hashlib.sha256((ROOT / 'requirements.lock').read_bytes()).hexdigest()
    except OSError:
        return False


def shortcuts_installed():
    """The video-trans command and desktop entry Launch & Bind reads actions from."""
    applications = Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share')) / 'applications'
    return (Path.home() / '.local/bin/video-trans').is_file() and (applications / 'video-trans.desktop').is_file()


def install_shortcuts():
    try:
        code, output = run_bounded(['bash', str(ROOT / 'install-shortcuts.sh')], 16384, 30.0)
    except (ValueError, TimeoutError):
        code, output = 1, b''
    if code or not shortcuts_installed():
        lines = [line for line in output.decode('utf-8', 'replace').splitlines() if line.strip()]
        raise RuntimeError(lines[-1][:300] if lines else 'Could not add the shortcut actions.')


def whisper_cached(model):
    """True when the pinned model is in the verified private store; other names (a local
    model folder) are checked when Start loads them."""
    if model not in WHISPER:
        return True
    return whisper_store.verified(model)


def loopback(url):
    try:
        return urlparse(url).hostname in ('localhost', '127.0.0.1', '::1')
    except ValueError:
        return False


def answers(url, path, timeout=0.5):
    """A loopback provider answers an HTTP request within one overall deadline.

    Never used for remote hosts. Reads at most the 1 KiB status line, so whatever
    listens on the port (possibly another local account) can neither stall the
    check nor make it allocate: only "HTTP/1.x <code>" below 500 counts.
    """
    if not loopback(url):
        return False
    parsed = urlparse(url)
    port = parsed.port or (443 if parsed.scheme == 'https' else 80)
    if parsed.scheme != 'http':
        return False
    deadline = time.monotonic() + timeout
    try:
        with socket.create_connection((parsed.hostname, port), timeout=timeout) as connection:
            target = (parsed.path.rstrip('/') + path) or '/'
            connection.sendall(f'GET {target} HTTP/1.0\r\nHost: {parsed.hostname}\r\nConnection: close\r\n\r\n'.encode())
            data = b''
            while b'\r\n' not in data and len(data) < 1024:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                connection.settimeout(remaining)
                chunk = connection.recv(1024 - len(data))
                if not chunk:
                    break
                data += chunk
    except (OSError, ValueError):
        return False
    match = re.match(rb'HTTP/1\.[01] (\d{3}) ', data)
    return bool(match) and int(match.group(1)) < 500


def user_service(unit):
    try:
        return subprocess.run(['systemctl', '--user', 'cat', unit], stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, timeout=3).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def local_available(kind, url):
    """The provider answers now, or Video Trans can start it on Start."""
    if kind == 'Ollama':
        return answers(url, '/api/tags') or user_service('ollama.service') or bool(shutil.which('ollama'))
    return answers(url, '/health') or user_service('llama-server.service')


def default_device(kind):
    command = ['pactl', 'get-default-sink' if kind == 'Audio output' else 'get-default-source']
    try:
        code, output = run_bounded(command, 4096, 3.0)
    except (OSError, ValueError, TimeoutError):
        return ''
    name = output.decode('utf-8', 'replace').strip() if code == 0 else ''
    return name + '.monitor' if name and kind == 'Audio output' else name


def short(text, limit=38):
    return text if len(text) <= limit else text[:limit - 1].rstrip() + '…'


def step(key, label, problem='', fixes=()):
    return dict(id=key, label=label, ok=not problem, problem=problem, fixes=list(fixes))


def runtime_step():
    missing = missing_packages()
    if runtime_ready() and not missing:
        return step('runtime', 'Runtime')
    parts = []
    if not runtime_ready():
        parts.append('a private Python runtime with Whisper (about 300 MB)')
    if missing:
        parts.append('the system packages ' + ', '.join(missing))
    return step('runtime', 'Runtime', 'Video Trans needs a one-time setup: ' + ' and '.join(parts) + '.',
                [dict(label='Set up now', action='setup')])


def device_step(settings, outputs):
    kind = settings.get('audio_input', 'Audio output')
    other = 'Microphone' if kind == 'Audio output' else 'Audio output'
    switch = dict(label='Capture ' + other.lower() + ' instead', settings=dict(audio_input=other, output=''))
    names = [device['name'] for device in outputs]
    if settings.get('output') in names:
        return step('device', 'Audio device')
    if not outputs:
        what = 'playback devices' if kind == 'Audio output' else 'microphones'
        return step('device', 'Audio device', f'No {what} found. Connect one, then refresh.',
                    [dict(label='Refresh devices', action='outputs'), switch])
    preferred = default_device(kind)
    ordered = sorted(outputs, key=lambda device: device['name'] != preferred)
    if settings.get('output'):
        problem = 'The selected audio device is not connected. Choose another one.'
    elif kind == 'Audio output':
        problem = 'Choose which playback device to caption. Its sound is captured, not your microphone.'
    else:
        problem = 'Choose which microphone to caption.'
    fixes = [dict(label='Use ' + short(device['label']), settings=dict(output=device['name'])) for device in ordered[:3]]
    return step('device', 'Audio device', problem, fixes + [switch])


def whisper_step(settings):
    model = settings.get('speech_model', 'small')
    if whisper_cached(model):
        return step('whisper', 'Speech recognition')
    size = WHISPER[model][1]
    fixes = [dict(label=f'Download Whisper {model} ({size})', action='download')]
    if model not in ('tiny', 'base', 'small'):
        fixes.append(dict(label='Use Whisper small instead (480 MB)', settings=dict(speech_model='small')))
    return step('whisper', 'Speech recognition',
                f'Speech recognition needs the Whisper {model} model, downloaded once (about {size}).', fixes)


def provider_step(settings, key_ready):
    kind, url = settings.get('provider', 'llama.cpp'), settings.get('endpoint', '')
    online = dict(label='Connect an online provider…', panel='provider',
                  settings=dict(provider='Online', endpoint=ENDPOINTS['Online'], model=''))
    if kind == 'Online':
        if key_ready or loopback(url):
            return step('provider', 'Translation provider')
        return step('provider', 'Translation provider',
                    'Enter the API key or bearer token for ' + (url or 'your online provider') + '.',
                    [dict(label='Enter API key…', panel='provider')])
    if not loopback(url) or local_available(kind, url):
        return step('provider', 'Translation provider')
    other = 'Ollama' if kind == 'llama.cpp' else 'llama.cpp'
    fixes = []
    if local_available(other, ENDPOINTS[other]):
        fixes.append(dict(label='Use ' + other + ' instead', settings=dict(provider=other, endpoint=ENDPOINTS[other], model='')))
    fixes.append(online)
    problem = (f'{kind} is not installed or has no user service. ' +
               ('Use ' + other + ', which is installed.' if len(fixes) > 1 else
                'Install llama.cpp or Ollama for local translation, or connect an online provider.'))
    return step('provider', 'Translation provider', problem, fixes)


def model_step(settings):
    if settings.get('model', '').strip():
        return step('model', 'Translation model')
    target = settings.get('target', 'German')
    if settings.get('provider') == 'Online':
        return step('model', 'Translation model', 'Enter the model ID your online provider should use.',
                    [dict(label='Enter model…', panel='provider')])
    return step('model', 'Translation model', f'Choose a translation model for {target}.',
                [dict(label='Choose a model automatically', action='suggest'),
                 dict(label='Load the model list', action='models')])


def steps(state):
    """Ordered setup steps; the popup offers the first failed one with its fixes."""
    first = runtime_step()
    if not first['ok']:
        return [first]
    settings = state.get('settings', {})
    result = [first, device_step(settings, state.get('outputs', [])), whisper_step(settings),
              provider_step(settings, state.get('key_ready', False))]
    if result[-1]['ok']:
        result.append(model_step(settings))
    return result


def setup_status():
    try:
        data = json.loads(status_path().read_text())
    except (OSError, ValueError):
        return dict(busy=False, phase='', message='')
    if not isinstance(data, dict):
        return dict(busy=False, phase='', message='')
    # A crashed setup leaves busy=true behind; trust it only while its process lives.
    if data.get('busy') and not Path(f"/proc/{int(data.get('pid', 0))}").exists():
        data.update(busy=False, phase='error', message='Setup stopped unexpectedly. Try again.')
    return dict(busy=bool(data.get('busy')), phase=str(data.get('phase', '')), message=str(data.get('message', '')))


def report(phase, message, busy=True, echo=None):
    save_json(status_path(), dict(busy=busy, phase=phase, message=message, pid=os.getpid()))
    if echo:
        echo(message)


PACKAGE_DEADLINE = 20 * 60  # seconds for the password prompt and the package transaction


def install_packages(packages, deadline=PACKAGE_DEADLINE):
    """pkexec pacman with a deadline. pkexec keeps this user's real UID, so a prompt left
    open is ended (TERM, then KILL); a pacman transaction already running as root cannot
    be signalled by this user and is never interrupted, so setup reports the failure and
    pacman's own lock keeps the system consistent."""
    proc = subprocess.Popen(['pkexec', 'pacman', '-S', '--needed', '--noconfirm', *packages],
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        return proc.wait(timeout=deadline)
    except subprocess.TimeoutExpired:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        return 1


SETUP_DEADLINE = 45 * 60   # seconds for setup.sh (runtime packages) in total
SETUP_TAIL = 4096


def run_runtime_setup(deadline=SETUP_DEADLINE):
    """Runs setup.sh in its own transient systemd scope with a hard total deadline.
    Only the last 4 KiB of its output are kept, in memory. When it ends, or the deadline
    passes, the scope is stopped, which ends and waits for every process it started
    (whatever they did to their process group) before setup reports anything."""
    scope = 'video-trans-setup-' + os.urandom(8).hex() + '.scope'
    proc = subprocess.Popen(['systemd-run', '--user', '--scope', '--quiet', '--collect', '--unit=' + scope,
                             '-p', 'TimeoutStopSec=10s', '--', 'bash', str(ROOT / 'setup.sh')],
                            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    tail, timed_out = b'', False
    end = time.monotonic() + deadline
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(proc.stdout, selectors.EVENT_READ)
            while True:
                left = end - time.monotonic()
                if left <= 0:
                    timed_out = True
                    break
                if not selector.select(min(left, 1.0)):
                    continue
                chunk = os.read(proc.stdout.fileno(), 65536)
                if not chunk:
                    break
                tail = (tail + chunk)[-SETUP_TAIL:]
    finally:
        # Ends everything still in the scope (TERM, KILL after 10 s) and waits for it.
        try:
            subprocess.run(['systemctl', '--user', 'stop', scope], stdin=subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
        except subprocess.TimeoutExpired:
            proc.kill()
        proc.stdout.close()
        code = proc.wait()
    if timed_out:
        return 1, 'Runtime setup took longer than 45 minutes and was stopped.'
    return code, tail.decode('utf-8', 'replace')


def run_setup(echo=None):
    """Install missing system packages (pkexec), the runtime and the shortcut entries."""
    flags = os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0)
    fd = os.open(str(runtime_dir() / f'video-trans-setup-{os.getuid()}.lock'), flags, 0o600)
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
        os.close(fd)
        raise RuntimeError('Refusing a setup lock that is not a private regular file.')
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        raise RuntimeError('Setup is already running.')
    try:
        packages = missing_packages()
        if packages:
            report('packages', 'Installing ' + ', '.join(packages) + ' · confirm the password prompt…', echo=echo)
            if install_packages(packages):
                raise RuntimeError('Installing ' + ', '.join(packages) + ' was cancelled or failed.')
        report('runtime', 'Preparing the private Python runtime and Whisper (a few minutes the first time)…', echo=echo)
        code, tail = run_runtime_setup()
        if code:
            lines = [line for line in tail.splitlines() if line.strip()]
            raise RuntimeError('Runtime setup failed: ' + (lines[-1][:300] if lines else 'see setup.sh output'))
        report('done', 'Setup finished. Next: choose your audio device.', busy=False, echo=echo)
    except Exception as exc:
        report('error', str(exc), busy=False, echo=echo)
        raise
    finally:
        os.close(fd)


def start_setup():
    """Run setup detached, so closing the popup does not interrupt it."""
    if setup_status()['busy']:
        return
    report('starting', 'Starting setup…')
    subprocess.Popen([sys.executable, str(ROOT / 'bridge.py'), 'setup'], stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def run_bounded(args, limit, timeout):
    """Run a helper with an output cap and one deadline: (returncode, bytes)."""
    deadline = time.monotonic() + timeout
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
    chunks, size = [], 0
    try:
        os.set_blocking(proc.stdout.fileno(), False)
        while True:
            if time.monotonic() > deadline:
                raise TimeoutError('took too long')
            try:
                chunk = os.read(proc.stdout.fileno(), 4096)
            except BlockingIOError:
                time.sleep(0.01)
                continue
            if not chunk:
                break
            size += len(chunk)
            if size > limit:
                raise ValueError('too large')
            chunks.append(chunk)
        return proc.wait(timeout=max(0.1, deadline - time.monotonic())), b''.join(chunks)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        proc.stdout.close()


def read_clipboard():
    """Explicit paste (Ctrl+V in a popup field): plain text, at most 8 KiB within 2 s."""
    try:
        code, offered = run_bounded(['wl-paste', '--list-types'], 4096, 1.0)
    except (OSError, ValueError, TimeoutError):
        return dict(clipboard='')
    mime = next((t for t in PASTE_TYPES if t in offered.decode('utf-8', 'replace').split()), None) if code == 0 else None
    if not mime:
        return dict(clipboard='')
    try:
        code, data = run_bounded(['wl-paste', '--no-newline', '--type', mime], PASTE_LIMIT, 2.0)
    except ValueError:
        raise ValueError('Clipboard text is longer than 8 KiB; paste a shorter value.')
    except TimeoutError:
        raise ValueError('The clipboard did not answer in time.')
    text = data.decode('utf-8', 'replace') if code == 0 else ''
    return dict(clipboard=''.join(c for c in text if c >= ' ' and c != '\x7f'))
