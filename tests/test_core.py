import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
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


if __name__ == '__main__':
    unittest.main()
