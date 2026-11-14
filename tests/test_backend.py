import json
from pathlib import Path
import queue
import sys
import threading
import unittest
from unittest.mock import patch, Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import Backend
from core import DEFAULTS


class LifecycleTests(unittest.TestCase):
    def test_whisper_download_does_not_start_translation_or_capture(self):
        backend = Backend()
        backend.jobs.put({'action': 'download', 'settings': DEFAULTS | {'speech_model': 'medium'}})
        backend.jobs.put({'action': 'quit'})
        with patch.object(backend, 'download_speech') as download, patch.object(backend, 'configure') as configure, patch.object(backend, 'run_capture') as capture, patch('backend.emit') as emit:
            backend.work()
        download.assert_called_once_with(DEFAULTS | {'speech_model': 'medium'})
        configure.assert_not_called()
        capture.assert_not_called()
        self.assertTrue(any(c.args[0] == 'downloaded' and c.kwargs['model'] == 'medium' for c in emit.call_args_list))

    def test_startup_checks_verify_local_model_and_audio(self):
        backend = Backend()
        backend.provider = Mock()
        backend.provider.models.return_value = ['translator']
        with patch.object(backend, 'configure'), patch('backend.capture_command'), patch('backend.shutil.which', return_value='/bin/tool'), patch('backend.importlib.util.find_spec', return_value=object()), patch('backend.emit') as emit:
            backend.quick_check({'settings': DEFAULTS | {'model': 'translator'}})
        checks = {c.kwargs['id']: c.kwargs for c in emit.call_args_list if c.args[0] == 'check'}
        self.assertEqual(checks['model']['status'], 'ok')
        self.assertEqual(checks['audio']['status'], 'ok')
        self.assertEqual(checks['target']['detail'], 'German')

    def test_startup_rejects_missing_local_model(self):
        backend = Backend()
        backend.provider = Mock()
        backend.provider.models.return_value = ['other-model']
        with patch.object(backend, 'configure'), patch('backend.capture_command'), patch('backend.shutil.which', return_value='/bin/tool'), patch('backend.importlib.util.find_spec', return_value=object()), patch('backend.emit') as emit:
            with self.assertRaisesRegex(ValueError, 'unavailable'):
                backend.quick_check({'settings': DEFAULTS | {'model': 'missing-model'}})
        self.assertTrue(any(c.kwargs.get('id') == 'model' and c.kwargs.get('status') == 'error' for c in emit.call_args_list))

    def test_english_only_whisper_cannot_auto_detect_other_languages(self):
        backend = Backend()
        with patch('backend.capture_command'), patch('backend.shutil.which', return_value='/bin/tool'), patch('backend.importlib.util.find_spec', return_value=object()), patch('backend.emit') as emit:
            with self.assertRaisesRegex(ValueError, 'multilingual'):
                backend.quick_check({'settings': DEFAULTS | {'model': 'translator', 'speech_model': 'tiny.en'}})
        self.assertTrue(any(c.kwargs.get('id') == 'whisper' and c.kwargs.get('status') == 'error' for c in emit.call_args_list))

    def test_stop_terminates_capture_and_download(self):
        backend = Backend()
        backend.capture = Mock()
        backend.capture.poll.return_value = None
        backend.download = Mock()
        backend.download.poll.return_value = None
        backend.cancel()
        self.assertTrue(backend.stop.is_set())
        backend.capture.terminate.assert_called_once()
        backend.download.terminate.assert_called_once()

    def test_cleanup_releases_speech_and_provider(self):
        backend = Backend()
        backend.speech = object()
        provider = backend.provider = Mock()
        provider.close.return_value = []
        backend.cleanup()
        self.assertIsNone(backend.speech)
        self.assertIsNone(backend.provider)
        provider.close.assert_called_once()

    def test_cancelled_queued_job_cannot_restart_capture(self):
        backend = Backend()
        backend.stop.set()
        backend.jobs.put({'action': 'start'})
        with patch.object(backend, 'run_capture') as capture, patch('backend.emit'):
            backend.work()
            capture.assert_not_called()

    def test_model_discovery_failure_cleans_started_provider(self):
        backend = Backend()
        provider = backend.provider = Mock()
        provider.models.side_effect = RuntimeError('unavailable')
        provider.close.return_value = []
        backend.jobs.put({'action': 'models'})
        with patch.object(backend, 'configure'), patch('backend.emit'):
            backend.work()
        provider.close.assert_called_once()

    def test_online_token_is_not_forwarded_to_auto_selected_local_provider(self):
        backend = Backend()
        provider = backend.provider = Mock()
        provider.models.return_value = ['gemma-4-E2B-it-Q4_K_M']
        provider.close.return_value = []
        backend.jobs.put({'action': 'suggest', 'token': 'online-secret',
                          'settings': {'provider': 'Online', 'endpoint': 'https://example.org', 'target': 'German'}})
        backend.jobs.put({'action': 'quit'})
        with patch('backend.local_provider_choice', return_value='llama.cpp'), patch.object(backend, 'configure') as configure, patch('backend.emit'):
            backend.work()
        self.assertEqual(configure.call_args.args[0]['token'], '')
        self.assertEqual(configure.call_args.args[0]['settings']['provider'], 'llama.cpp')


if __name__ == '__main__':
    unittest.main()


class PinnedDownloadTests(unittest.TestCase):
    def backend(self):
        import backend
        subject = backend.Backend()
        subject.check = Mock()
        return backend, subject

    def test_download_fetches_exactly_the_pinned_revision_and_checks_its_hash(self):
        backend, subject = self.backend()
        child = Mock(); child.poll.return_value = 0; child.returncode = 0
        with patch.object(backend, 'whisper_verified', return_value=False), \
             patch.object(backend, 'mark_whisper_verified') as mark, \
             patch.object(backend.subprocess, 'Popen', return_value=child) as popen, patch.object(backend, 'emit'):
            subject.download_speech({'speech_model': 'small'})
        argv = popen.call_args.args[0]
        repo, _, revision, digest = backend.WHISPER['small']
        self.assertEqual(argv[-3:], [repo, revision, digest])
        self.assertIn('download_model(repo, revision=revision', argv[2])
        self.assertIn('hashlib.sha256', argv[2])
        mark.assert_called_once_with('small')

    def test_checksum_mismatch_is_refused_and_not_recorded(self):
        backend, subject = self.backend()
        child = Mock(); child.poll.return_value = 3; child.returncode = 3
        with patch.object(backend, 'whisper_verified', return_value=False), \
             patch.object(backend, 'mark_whisper_verified') as mark, \
             patch.object(backend.subprocess, 'Popen', return_value=child), patch.object(backend, 'emit'):
            with self.assertRaises(RuntimeError) as raised:
                subject.download_speech({'speech_model': 'small'})
        self.assertIn('checksum', str(raised.exception))
        mark.assert_not_called()

    def test_download_has_a_hard_deadline(self):
        backend, subject = self.backend()
        child = Mock(); child.poll.return_value = None
        with patch.object(backend, 'whisper_verified', return_value=False), patch.object(backend, 'DOWNLOAD_DEADLINE', 0), \
             patch.object(backend.subprocess, 'Popen', return_value=child), patch.object(backend, 'emit'):
            with self.assertRaises(RuntimeError):
                subject.download_speech({'speech_model': 'small'})
        child.terminate.assert_called_once()
        self.assertIsNone(subject.download)

    def test_verified_model_needs_no_download_and_unknown_names_are_refused(self):
        backend, subject = self.backend()
        with patch.object(backend, 'whisper_verified', return_value=True), \
             patch.object(backend.subprocess, 'Popen') as popen, patch.object(backend, 'emit'):
            subject.download_speech({'speech_model': 'small'})
            popen.assert_not_called()
            with self.assertRaises(ValueError):
                subject.download_speech({'speech_model': '../../evil'})

    def test_only_pinned_models_or_local_folders_are_loaded(self):
        import backend, tempfile
        self.assertTrue(backend.speech_model_path('small').endswith(backend.WHISPER['small'][2]))
        for name in ('tiny.en', 'Systran/faster-whisper-small', '../models', 'relative/folder', ''):
            with self.assertRaises(ValueError):
                backend.speech_model_path(name)
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                backend.speech_model_path(folder)                      # no model.bin
            (Path(folder) / 'model.bin').write_bytes(b'')
            self.assertEqual(backend.speech_model_path(folder), folder)
