import json
from pathlib import Path
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import readiness
from core import DEFAULTS

OUTPUTS = [dict(name='hdmi.monitor', label='HDMI'), dict(name='usb.monitor', label='USB speakers')]


class StepTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        cache = Path(self.directory.name)
        self.patches = [patch.dict(os.environ, HF_HUB_CACHE=str(cache)),
                        patch.object(readiness.whisper_store, 'verified', side_effect=lambda model: model == 'small'),
                        patch.object(readiness, 'runtime_ready', return_value=True),
                        patch.object(readiness, 'missing_packages', return_value=[]),
                        patch.object(readiness, 'default_device', return_value='usb.monitor'),
                        patch.object(readiness, 'local_available', return_value=True)]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.directory.cleanup()

    def state(self, **settings):
        return dict(settings=DEFAULTS | dict(output='hdmi.monitor', model='gemma') | settings, outputs=OUTPUTS, key_ready=False)

    def failed(self, state):
        return [step for step in readiness.steps(state) if not step['ok']]

    def test_configured_setup_is_ready(self):
        self.assertEqual(self.failed(self.state()), [])

    def test_missing_runtime_is_the_only_step(self):
        with patch.object(readiness, 'runtime_ready', return_value=False), \
             patch.object(readiness, 'missing_packages', return_value=['ffmpeg']):
            steps = readiness.steps(self.state(output=''))
        self.assertEqual([step['id'] for step in steps], ['runtime'])
        self.assertIn('ffmpeg', steps[0]['problem'])
        self.assertEqual(steps[0]['fixes'][0], dict(label='Set up now', action='setup'))

    def test_device_fix_offers_default_first_and_other_input(self):
        step = self.failed(self.state(output=''))[0]
        self.assertEqual(step['id'], 'device')
        self.assertEqual(step['fixes'][0]['settings'], dict(output='usb.monitor'))
        self.assertEqual(step['fixes'][-1]['settings'], dict(audio_input='Microphone', output=''))
        disconnected = self.failed(self.state(output='gone.monitor'))[0]
        self.assertIn('not connected', disconnected['problem'])

    def test_no_devices_offers_refresh(self):
        state = self.state(output='')
        state['outputs'] = []
        self.assertEqual(self.failed(state)[0]['fixes'][0]['action'], 'outputs')

    def test_whisper_download_needed_until_cached(self):
        step = self.failed(self.state(speech_model='medium'))[0]
        self.assertEqual(step['id'], 'whisper')
        self.assertEqual(step['fixes'][0]['action'], 'download')
        self.assertEqual(step['fixes'][1]['settings'], dict(speech_model='small'))

    def test_missing_local_provider_suggests_alternatives(self):
        with patch.object(readiness, 'local_available', side_effect=lambda kind, url: kind == 'Ollama'):
            step = self.failed(self.state())[0]
        self.assertEqual(step['id'], 'provider')
        self.assertEqual(step['fixes'][0]['settings']['provider'], 'Ollama')
        self.assertEqual(step['fixes'][-1]['panel'], 'provider')

    def test_online_needs_token_then_model(self):
        online = dict(provider='Online', endpoint='https://api.openai.com/v1', model='')
        self.assertEqual(self.failed(self.state(**online))[0]['fixes'][0]['panel'], 'provider')
        state = self.state(**online)
        state['key_ready'] = True
        self.assertEqual(self.failed(state)[0]['id'], 'model')

    def test_missing_model_is_chosen_automatically(self):
        step = self.failed(self.state(model=''))[0]
        self.assertEqual(step['fixes'][0]['action'], 'suggest')

    def test_stale_busy_setup_is_reported_as_stopped(self):
        with patch.object(readiness, 'status_path', return_value=Path(self.directory.name) / 'setup.json'):
            readiness.save_json(readiness.status_path(), dict(busy=True, phase='runtime', message='x', pid=2 ** 22 + 7))
            status = readiness.setup_status()
        self.assertFalse(status['busy'])
        self.assertEqual(status['phase'], 'error')


class HostileInputTests(unittest.TestCase):
    """Whatever listens on a loopback port (another account, too) is untrusted."""

    def serve(self, handler):
        import socket, threading
        server = socket.socket()
        server.bind(('127.0.0.1', 0))
        server.listen()
        def run():
            try:
                connection, _ = server.accept()
                with connection:
                    handler(connection)
            except OSError:
                pass
        threading.Thread(target=run, daemon=True).start()
        self.addCleanup(server.close)
        return 'http://127.0.0.1:%d' % server.getsockname()[1]

    def timed(self, url):
        import time
        start = time.monotonic()
        result = readiness.answers(url, '/health', timeout=0.5)
        return result, time.monotonic() - start

    def test_real_http_reply_counts(self):
        url = self.serve(lambda c: (c.recv(1024), c.sendall(b'HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok')))
        self.assertEqual(self.timed(url)[0], True)

    def test_drip_status_line_hits_one_deadline(self):
        import time
        def drip(connection):
            connection.recv(1024)
            for byte in b'HTTP/1.1 200 OK':
                connection.sendall(bytes([byte]))
                time.sleep(0.1)
        result, elapsed = self.timed(self.serve(drip))
        self.assertFalse(result)
        self.assertLess(elapsed, 1.0)

    def test_endless_garbage_is_capped(self):
        def flood(connection):
            connection.recv(1024)
            try:
                while True:
                    connection.sendall(b'x' * 65536)
            except OSError:
                pass
        result, elapsed = self.timed(self.serve(flood))
        self.assertFalse(result)
        self.assertLess(elapsed, 1.0)

    def test_silent_server_and_server_errors(self):
        self.assertFalse(self.timed(self.serve(lambda c: c.recv(1024)))[0])
        self.assertFalse(self.timed(self.serve(lambda c: (c.recv(1024), c.sendall(b'HTTP/1.1 503 x\r\n\r\n'))))[0])

    def test_remote_and_https_endpoints_are_never_contacted(self):
        with patch.object(readiness.socket, 'create_connection') as connect:
            self.assertFalse(readiness.answers('http://example.com', '/health'))
            self.assertFalse(readiness.answers('https://127.0.0.1:8443', '/health'))
        connect.assert_not_called()

    def test_setup_lock_symlink_is_refused(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(readiness, 'runtime_dir', return_value=Path(directory)):
            target = Path(directory, 'target')
            target.write_text('keep')
            Path(directory, f'video-trans-setup-{os.getuid()}.lock').symlink_to(target)
            with patch.object(readiness, 'status_path', return_value=Path(directory, 'status.json')):
                with self.assertRaises(OSError):
                    readiness.run_setup()
            self.assertEqual(target.read_text(), 'keep')


class ShortcutTests(unittest.TestCase):
    def test_install_creates_managed_entries_and_keeps_foreign_ones(self):
        with tempfile.TemporaryDirectory() as home:
            env = {'HOME': home, 'XDG_DATA_HOME': home + '/.local/share'}
            with patch.dict(os.environ, env), patch.object(readiness.Path, 'home', return_value=Path(home)):
                self.assertFalse(readiness.shortcuts_installed())
                readiness.install_shortcuts()
                self.assertTrue(readiness.shortcuts_installed())
                desktop = Path(home, '.local/share/applications/video-trans.desktop').read_text()
                self.assertIn('[Desktop Action StartCaptions]', desktop)
                launcher = Path(home, '.local/bin/video-trans')
                self.assertIn('# Managed by ubruckhaus.video-trans', launcher.read_text())
                launcher.write_text('#!/bin/sh\necho mine\n')
                readiness.install_shortcuts()
                self.assertEqual(launcher.read_text(), '#!/bin/sh\necho mine\n')


class BridgeOfflineTests(unittest.TestCase):
    def test_offline_configure_writes_known_settings_only(self):
        import bridge, core
        with tempfile.TemporaryDirectory() as directory, patch.object(core, 'CONFIG', Path(directory)):
            bridge.save_offline(dict(target='French', font_size=30.0, width=5, evil='x'))
            settings = core.load_settings()
        self.assertEqual((settings['target'], settings['font_size']), ('French', 30))
        self.assertNotIn('evil', settings)


if __name__ == '__main__':
    unittest.main()


class WhisperPinTests(unittest.TestCase):
    def store(self, folder):
        import whisper_store
        return patch.object(whisper_store, 'STORE', Path(folder) / 'whisper')

    def write_model(self, target, files):
        target.mkdir(parents=True, exist_ok=True)
        for name, content in files.items():
            (target / name).write_bytes(content)

    def test_only_a_fully_matching_download_enters_the_store(self):
        import hashlib, whisper_store
        files = {'model.bin': b'weights', 'config.json': b'{}'}
        pinned = {'model.bin': 'sha256:' + hashlib.sha256(b'weights').hexdigest(),
                  'config.json': 'gitsha1:' + hashlib.sha1(b'blob 2\0{}').hexdigest()}
        with tempfile.TemporaryDirectory() as folder, self.store(folder), \
             patch.dict(whisper_store.MODELS, {'tiny': ('repo/tiny', '1 MB', 'a' * 40, pinned)}):
            store = whisper_store.private_store()
            self.assertEqual(oct(store.stat().st_mode & 0o777), '0o700')
            bad = store / '.download-bad'; self.write_model(bad, files | {'model.bin': b'tampered'})
            self.assertFalse(whisper_store.adopt('tiny', bad))
            self.assertFalse(bad.exists()); self.assertFalse(whisper_store.verified('tiny'))
            good = store / '.download-good'; self.write_model(good, files)
            self.assertTrue(whisper_store.adopt('tiny', good))
            self.assertTrue(whisper_store.verified('tiny'))
            self.assertEqual(whisper_store.folder('tiny').name, 'tiny-' + 'a' * 40)
            # A symlink swapped in later is not accepted.
            target = whisper_store.folder('tiny') / 'model.bin'
            target.unlink(); target.symlink_to('/etc/hostname')
            self.assertFalse(whisper_store.verified('tiny'))

    def test_symlinked_download_files_are_rejected(self):
        import hashlib, whisper_store
        with tempfile.TemporaryDirectory() as folder, self.store(folder):
            outside = Path(folder) / 'outside.bin'; outside.write_bytes(b'weights')
            pinned = {'model.bin': 'sha256:' + hashlib.sha256(b'weights').hexdigest()}
            with patch.dict(whisper_store.MODELS, {'tiny': ('repo/tiny', '1 MB', 'b' * 40, pinned)}):
                download = whisper_store.private_store() / '.download-x'; download.mkdir()
                (download / 'model.bin').symlink_to(outside)
                self.assertFalse(whisper_store.adopt('tiny', download))

    def test_every_offered_model_pins_a_commit_and_every_file(self):
        for model, (repo, size, revision, files) in readiness.WHISPER.items():
            self.assertRegex(revision, r'^[0-9a-f]{40}$', model)
            self.assertIn('model.bin', files)
            self.assertRegex(files['model.bin'], r'^sha256:[0-9a-f]{64}$')
            for name, expected in files.items():
                self.assertRegex(expected, r'^(sha256:[0-9a-f]{64}|gitsha1:[0-9a-f]{40})$', (model, name))

    def test_runtime_needs_the_current_lock_record(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder); (data / 'runtime/bin').mkdir(parents=True)
            python = data / 'runtime/bin/python'; python.write_text(''); python.chmod(0o755)
            with patch.object(readiness, 'DATA', data), patch.object(readiness, 'RUNTIME_PYTHON', python):
                self.assertFalse(readiness.runtime_ready())
                import hashlib
                (data / 'runtime/.verified-lock').write_text(hashlib.sha256((readiness.ROOT / 'requirements.lock').read_bytes()).hexdigest() + '\n')
                self.assertTrue(readiness.runtime_ready())

    def test_requirements_lock_pins_every_package_with_hashes(self):
        import re
        entries = re.split(r'\n(?=\S)', '\n'.join(l for l in (readiness.ROOT / 'requirements.lock').read_text().splitlines()
                                                 if l.strip() and not l.startswith('#')))
        self.assertGreater(len(entries), 20)
        for entry in entries:
            self.assertRegex(entry, r'^[a-z0-9][a-z0-9._-]*==\S+ ')
            self.assertRegex(entry, r'--hash=sha256:[0-9a-f]{64}')

    def test_setup_script_rebuilds_from_the_hashed_lock(self):
        script = (readiness.ROOT / 'setup.sh').read_text()
        self.assertIn('--require-hashes', script)
        self.assertIn('--only-binary :all:', script)
        self.assertIn('--reinstall', script)
        self.assertIn('uv pip sync', script)
        self.assertIn('python_version=3.12.14', script)
        self.assertIn('--managed-python', script)

    def test_package_install_has_a_deadline(self):
        import subprocess
        real_popen = subprocess.Popen
        with patch('readiness.subprocess.Popen', side_effect=lambda argv, **kw: real_popen(['sleep', '30'])) as popen:
            import time
            start = time.monotonic()
            self.assertEqual(readiness.install_packages(['ffmpeg'], deadline=1), 1)
            self.assertLess(time.monotonic() - start, 4)
        self.assertEqual(popen.call_args.args[0][:4], ['pkexec', 'pacman', '-S', '--needed'])

    def test_runtime_setup_has_a_deadline_and_ends_its_scope(self):
        calls = []
        def fake_run(argv, **kwargs):
            calls.append(argv)
        import subprocess
        real_popen = subprocess.Popen
        started = []
        def fake_popen(argv, **kwargs):
            started.append(real_popen(['sleep', '30'], stdout=subprocess.PIPE, stdin=subprocess.DEVNULL))
            return started[-1]
        def stop_scope(scope):
            fake_run(['systemctl', '--user', 'stop', scope])
            started[-1].kill()   # what stopping the scope does to its processes
            return True
        with patch.object(readiness, 'ROOT', Path(tempfile.gettempdir())), \
             patch('readiness.subprocess.Popen', side_effect=fake_popen) as popen, \
             patch.object(readiness, 'scope_stopped', side_effect=stop_scope):
            import time
            start = time.monotonic()
            code, message = readiness.run_runtime_setup(deadline=1)
            self.assertLess(time.monotonic() - start, 4)
        self.assertEqual(code, 1)
        self.assertIn('45 minutes', message)
        self.assertEqual(calls[0][:3], ['systemctl', '--user', 'stop'])
        self.assertTrue(calls[0][3].startswith('video-trans-setup-') and calls[0][3].endswith('.scope'))
        argv = popen.call_args.args[0]
        self.assertEqual(argv[:4], ['systemd-run', '--user', '--scope', '--quiet'])


class ScopeStopTests(unittest.TestCase):
    def test_scope_counts_as_stopped_only_when_systemd_says_so(self):
        replies = iter(['active', 'activating', 'inactive'])
        def run(argv, **kwargs):
            return type('R', (), {'stdout': next(replies) if 'is-active' in argv else ''})()
        with patch('readiness.subprocess.run', side_effect=run), patch('readiness.time.sleep'):
            self.assertTrue(readiness.scope_stopped('video-trans-setup-x.scope'))
        with patch('readiness.subprocess.run', side_effect=OSError('no bus')), patch('readiness.time.sleep'):
            self.assertFalse(readiness.scope_stopped('video-trans-setup-x.scope'))
