import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import ppm_luminance, auto_bright, sample_region, caption_colors, backdrop_for, next_text_color, DEFAULTS as CORE_DEFAULTS
from core import Provider, capture_command, playback_outputs, microphone_inputs, clean_translation, save_json, DEFAULTS, suggest_model, read_theme, local_provider_choice


class PlaybackTests(unittest.TestCase):
    def test_only_sink_monitors_are_discovered(self):
        sinks = [dict(name='speakers', description='Speakers', monitor_source='speakers.monitor'),
                 dict(name='bad', monitor_source=42)]
        with patch('core.subprocess.run', return_value=Mock(stdout=json.dumps(sinks))) as run:
            self.assertEqual(playback_outputs(), [dict(name='speakers.monitor', label='Speakers')])
            self.assertEqual(run.call_args.args[0], ['pactl', '--format=json', 'list', 'sinks'])

    def test_microphone_and_stale_monitor_rejected(self):
        with patch('core.playback_outputs', return_value=[dict(name='speakers.monitor')]):
            for source in ('default', 'alsa_input.microphone', 'stale.monitor', ''):
                with self.assertRaises(ValueError):
                    capture_command(source)

    def test_filters_are_on_capture_and_can_be_disabled(self):
        with patch('core.playback_outputs', return_value=[dict(name='speakers.monitor')]):
            command = capture_command('speakers.monitor')
            self.assertEqual(command[command.index('-i') + 1], 'speakers.monitor')
            self.assertIn('afftdn', command[command.index('-af') + 1])
            command = capture_command('speakers.monitor', False)
            self.assertNotIn('afftdn', command[command.index('-af') + 1])

    def test_microphone_requires_explicit_mode(self):
        with patch('core.microphone_inputs', return_value=[dict(name='alsa_input.mic')]), patch('core.playback_outputs', return_value=[dict(name='speakers.monitor')]):
            with self.assertRaises(ValueError):
                capture_command('alsa_input.mic')
            command = capture_command('alsa_input.mic', input_kind='Microphone')
            self.assertEqual(command[command.index('-i') + 1], 'alsa_input.mic')
            with self.assertRaises(ValueError):
                capture_command('speakers.monitor', input_kind='Microphone')

    def test_microphone_list_excludes_monitors(self):
        sources = [dict(name='mic', monitor_of_sink=None), dict(name='sink.monitor', monitor_of_sink=1),
                   dict(name='renamed-monitor', monitor_of_sink=2)]
        with patch('core.subprocess.run', return_value=Mock(stdout=json.dumps(sources))):
            self.assertEqual(microphone_inputs(), [dict(name='mic', label='mic')])


class ProviderTests(unittest.TestCase):
    def provider(self, kind='llama.cpp'):
        return Provider(DEFAULTS | dict(provider=kind, model='translator'))

    def test_llama_translation_and_owned_model_unload(self):
        provider = self.provider()
        responses = [{'data': [{'id': 'translator', 'status': {'value': 'unloaded'}},
                               {'id': 'shared', 'status': {'value': 'loaded'}}]},
                     {'choices': [{'message': {'content': '<think>hidden</think> Guten Tag.'}}]},
                     {'success': True}]
        with patch.object(provider, 'request', side_effect=responses) as request, patch.object(provider, 'ensure_service'):
            self.assertEqual(provider.translate('Hello.', 'en'), 'Guten Tag.')
            provider.close()
            self.assertEqual(request.call_args.args, ('/models/unload', {'model': 'translator'}))
            body = request.call_args_list[1].args[1]
            self.assertEqual(body['messages'][1]['content'], 'Hello.')
            self.assertIn('German', body['messages'][0]['content'])

    def test_preloaded_model_is_not_unloaded(self):
        provider = self.provider()
        provider.snapshot_known = True
        provider.preloaded = {'translator'}
        provider.used_models = {'translator'}
        with patch.object(provider, 'request') as request:
            provider.close()
            request.assert_not_called()

    def test_ollama_unload_protocol(self):
        provider = self.provider('Ollama')
        provider.used_models = {'translator'}
        with patch.object(provider, 'request') as request:
            provider.close()
            self.assertEqual(request.call_args.args, ('/api/generate', dict(model='translator', keep_alive=0, stream=False)))

    def test_online_never_unloads_or_starts_local_service(self):
        provider = self.provider('Online')
        provider.used_models = {'translator'}
        with patch.object(provider, 'request') as request, patch('core.subprocess.run') as run:
            provider.ensure_service()
            provider.close()
            request.assert_not_called()
            run.assert_not_called()

    def test_owned_service_stops_even_when_unload_fails(self):
        provider = self.provider()
        provider.started_service = 'llama-server.service'
        provider.used_models = {'translator'}
        with patch.object(provider, 'request', side_effect=RuntimeError('offline')), patch('core.subprocess.run', return_value=Mock(returncode=0)) as run:
            self.assertTrue(provider.close())
            self.assertEqual(run.call_args.args[0], ['systemctl', '--user', 'stop', 'llama-server.service'])

    def test_existing_unhealthy_service_not_claimed(self):
        provider = self.provider()
        with patch.object(provider, 'request', side_effect=[RuntimeError(), {'status': 'ok'}]), patch('core.subprocess.run', return_value=Mock(returncode=0)):
            provider.ensure_service()
            self.assertIsNone(provider.started_service)
        provider.close()

    def test_remote_credentials_require_tls(self):
        with self.assertRaises(ValueError):
            Provider(DEFAULTS | dict(provider='Online', endpoint='http://example.org'), 'secret')

    def test_credentials_file_is_private(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'credentials.json'
            save_json(path, {'token': 'secret'})
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(json.loads(path.read_text()), {'token': 'secret'})

    def test_credentials_ignore_predictable_temp_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'credentials.json'
            victim = Path(directory) / 'other.json'
            victim.write_text('unchanged')
            path.with_suffix('.tmp').symlink_to(victim)
            save_json(path, {'token': 'secret'})
            self.assertEqual(victim.read_text(), 'unchanged')
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(json.loads(path.read_text()), {'token': 'secret'})

    def test_credentials_ignore_permissive_temp_and_replace_old_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'credentials.json'
            old_temp = path.with_suffix('.tmp')
            old_temp.write_text('unchanged')
            old_temp.chmod(0o666)
            path.write_text('old credentials')
            path.chmod(0o644)
            save_json(path, {'token': 'secret'})
            self.assertEqual(old_temp.read_text(), 'unchanged')
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(json.loads(path.read_text()), {'token': 'secret'})
            self.assertEqual(list(Path(directory).glob('.credentials.json.*.tmp')), [])

    def test_failed_credentials_save_preserves_old_file_and_removes_temp(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'credentials.json'
            save_json(path, {'token': 'old'})
            with patch('core.json.dump', side_effect=RuntimeError('write failed')):
                with self.assertRaises(RuntimeError):
                    save_json(path, {'token': 'new'})
            self.assertEqual(json.loads(path.read_text()), {'token': 'old'})
            self.assertEqual(list(Path(directory).glob('.credentials.json.*.tmp')), [])

    def test_unfinished_reasoning_not_shown(self):
        with self.assertRaises(ValueError):
            clean_translation('<think>still thinking')


class SuggestionAndThemeTests(unittest.TestCase):
    def test_target_language_changes_suggestion(self):
        models = ['gemma-4-E2B-it-Q4_K_M', 'qwen3-7b-instruct', 'qwen3-tts-0.6b', 'embedding-7b']
        self.assertEqual(suggest_model(models, 'German')[0], 'gemma-4-E2B-it-Q4_K_M')
        self.assertEqual(suggest_model(models, 'Chinese')[0], 'qwen3-7b-instruct')

    def test_no_suitable_model_is_reported(self):
        with self.assertRaises(ValueError):
            suggest_model(['tts-1b', 'embed-8b'], 'German')

    def test_local_installation_is_detected_when_switching_from_online(self):
        with patch('core.shutil.which', side_effect=lambda name: '/bin/ollama' if name == 'ollama' else None):
            self.assertEqual(local_provider_choice('Online'), 'Ollama')

    def test_theme_defaults_and_user_surface_overrides(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            theme = root / 'state/omarchy/current/theme'
            theme.mkdir(parents=True)
            (theme / 'colors.toml').write_text('background="#112233"\nforeground="#ddeeff"\naccent="#aabbcc"\n')
            (theme / 'shell.toml').write_text('[popups]\nbackground-alpha=0.8\nborder="hyprland.active-border"\n[hyprland]\nactive-border="#123456"\n')
            config = root / 'config/omarchy'
            config.mkdir(parents=True)
            (config / 'shell.toml').write_text('[popups]\nborder-width=4\n')
            with patch.dict(os.environ, XDG_STATE_HOME=str(root / 'state'), XDG_CONFIG_HOME=str(root / 'config')):
                result = read_theme()
            self.assertEqual(result['background_transparency'], 20)
            self.assertEqual(result['border_width'], 4)
            self.assertEqual(result['border_color'], '#123456')



class CaptionColourTests(unittest.TestCase):
    def test_default_is_automatic(self):
        self.assertEqual(CORE_DEFAULTS['text_color'], 'auto')

    def test_ppm_luminance_and_malformed_input(self):
        self.assertAlmostEqual(ppm_luminance(b'P6\n2 1\n255\n' + bytes([255] * 6)), 1.0)
        self.assertAlmostEqual(ppm_luminance(b'P6 1 1 255 ' + bytes([0, 0, 0])), 0.0)
        for bad in (b'', b'P3\n1 1\n255\n0 0 0', b'P6\n4 4\n255\n' + bytes(3), b'P6\n0 0\n255\n'):
            self.assertIsNone(ppm_luminance(bad))

    def test_hysteresis_and_unknown_measurement(self):
        self.assertFalse(auto_bright(False, 0.55))
        self.assertTrue(auto_bright(False, 0.65))
        self.assertTrue(auto_bright(True, 0.5))
        self.assertFalse(auto_bright(True, 0.4))
        self.assertTrue(auto_bright(True, None))

    def test_sample_region_avoids_the_captions(self):
        self.assertEqual(sample_region(100, 700, 1500, 240), (100, 640, 1500, 60))
        self.assertEqual(sample_region(100, 20, 1500, 240), (100, 260, 1500, 60))

    def test_colours(self):
        theme = dict(foreground='#e8eaf0', background='#15171c')
        self.assertEqual(caption_colors(theme, 'auto'), ('#ffffff', '#000000'))
        self.assertEqual(caption_colors(theme, 'auto', bright=True), ('#000000', '#ffffff'))
        self.assertEqual(caption_colors(theme, 'theme'), ('#e8eaf0', '#15171c'))
        self.assertEqual(caption_colors(theme, '<b>'), ('#e8eaf0', '#15171c'))
        self.assertEqual(backdrop_for('#ffe14d'), '#000000')
        self.assertEqual(backdrop_for('#1f4fd1'), '#ffffff')
        self.assertEqual(next_text_color('black'), 'auto')


if __name__ == '__main__':
    unittest.main()


class HostileProviderTests(unittest.TestCase):
    """The default endpoint is an unauthenticated loopback port another local account can occupy:
    every reply must stay bounded in bytes and time, and model IDs in number and shape."""

    def serve(self, handler):
        import socket, threading
        listener = socket.socket()
        listener.bind(('127.0.0.1', 0))
        listener.listen(4)
        stop = threading.Event()

        def run():
            listener.settimeout(0.2)
            while not stop.is_set():
                try:
                    client, _ = listener.accept()
                except OSError:
                    continue
                with client:
                    client.settimeout(0.2)
                    try:
                        client.recv(65536)
                        handler(client, stop)
                    except OSError:
                        pass
        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        self.addCleanup(lambda: (stop.set(), thread.join(2), listener.close()))
        provider = Provider(DEFAULTS | dict(endpoint='http://127.0.0.1:%d' % listener.getsockname()[1], model='m'))
        import httpx
        provider.client.timeout = httpx.Timeout(2)
        self.addCleanup(provider.client.close)
        return provider

    def test_endless_chunked_body_is_cut_at_the_cap(self):
        def endless(client, stop):
            client.sendall(b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nTransfer-Encoding: chunked\r\n\r\n')
            chunk = b'x' * 65536
            while not stop.is_set():
                client.sendall(b'%x\r\n' % len(chunk) + chunk + b'\r\n')
        provider = self.serve(endless)
        with self.assertRaises(ValueError):
            provider.request('/v1/models')

    def test_dripping_body_hits_the_overall_deadline(self):
        import time as timelib
        def drip(client, stop):
            client.sendall(b'HTTP/1.1 200 OK\r\nContent-Length: 1000000\r\n\r\n')
            while not stop.is_set():
                client.sendall(b'x')
                timelib.sleep(0.05)
        provider = self.serve(drip)
        started = timelib.monotonic()
        with self.assertRaises(TimeoutError):
            provider.request('/v1/models')
        self.assertLess(timelib.monotonic() - started, 10)

    def test_dripping_headers_hit_the_overall_deadline_and_client_recovers(self):
        import time as timelib
        calls = []
        def drip_headers(client, stop):
            calls.append(1)
            if len(calls) > 1:
                body = b'{"ok": true}'
                client.sendall(b'HTTP/1.1 200 OK\r\nContent-Length: %d\r\n\r\n' % len(body) + body)
                return
            client.sendall(b'HTTP/1.1 200 OK\r\n')
            while not stop.is_set():
                client.sendall(b'X-Drip: 1\r\n')
                timelib.sleep(0.05)
        provider = self.serve(drip_headers)
        started = timelib.monotonic()
        with self.assertRaises(TimeoutError):
            provider.request('/v1/models')
        self.assertLess(timelib.monotonic() - started, 10)
        self.assertEqual(provider.request('/v1/models'), {'ok': True})

    def test_huge_declared_length_is_refused_before_reading(self):
        def huge(client, stop):
            client.sendall(b'HTTP/1.1 200 OK\r\nContent-Length: 999999999999\r\n\r\n{}')
        with self.assertRaises(ValueError):
            self.serve(huge).request('/v1/models')

    def test_normal_reply_still_parses(self):
        body = json.dumps({'data': [{'id': 'qwen2.5:7b-instruct', 'status': {'value': 'loaded'}}]}).encode()
        def normal(client, stop):
            client.sendall(b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: %d\r\n\r\n' % len(body) + body)
        self.assertEqual(self.serve(normal).request('/v1/models')['data'][0]['id'], 'qwen2.5:7b-instruct')

    def test_model_ids_are_capped_in_number_length_and_shape(self):
        from core import clean_model_ids, MAX_MODELS
        hostile = ['ok-model', 'x' * 100000, 'bad\nline', '<b>html</b>', 42, None, ['list'], {'d': 1},
                   'ok-model', 'hf.co/org/Model-GGUF:Q4_K_M', ''] + ['m%d' % i for i in range(100000)]
        ids = clean_model_ids(hostile)
        self.assertEqual(ids[:2], ['ok-model', 'hf.co/org/Model-GGUF:Q4_K_M'])
        self.assertEqual(len(ids), MAX_MODELS)
        self.assertTrue(all(len(m) <= 160 for m in ids))
        self.assertEqual(clean_model_ids('not a list'), [])

    def test_models_survive_hostile_rows(self):
        from core import MAX_MODELS
        provider = Provider(DEFAULTS | dict(model='m'))
        rows = [{'id': ['unhashable'], 'status': 'loaded'}, {'id': {'x': 1}}, 'row', None,
                {'id': 'good', 'status': {'value': 'loaded'}}] + [{'id': 'm%d' % i} for i in range(5000)]
        with patch.object(provider, 'request', return_value={'data': rows}), patch.object(provider, 'ensure_service'):
            models = provider.models()
        self.assertEqual(models[0], 'good')
        self.assertLessEqual(len(models), MAX_MODELS)
        self.assertIn('good', provider.preloaded)
        ollama = Provider(DEFAULTS | dict(provider='Ollama', endpoint='http://127.0.0.1:11434', model='m'))
        with patch.object(ollama, 'request', side_effect=[{'models': [{'name': ['x']}, {'name': 'llama3'}]}, {'models': 'nope'}]), \
                patch.object(ollama, 'ensure_service'):
            self.assertEqual(ollama.models(), ['llama3'])
        for reply in ([], 'text', {'data': 'text'}, {'data': None}):
            fresh = Provider(DEFAULTS | dict(model='m'))
            with patch.object(fresh, 'request', return_value=reply), patch.object(fresh, 'ensure_service'):
                self.assertEqual(fresh.models(), [])

    def test_translation_is_capped(self):
        from core import MAX_CAPTION_CHARS
        self.assertEqual(len(clean_translation('a' * 10_000_000)), MAX_CAPTION_CHARS)
        with self.assertRaises(ValueError):
            clean_translation(['not', 'text'])
