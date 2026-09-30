import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['QT_QPA_PLATFORMTHEME'] = 'none'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
import gui
from core import DEFAULTS

APP = QApplication.instance() or QApplication([])


class WindowTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.patches = [patch.object(gui, 'CONFIG', Path(self.directory.name)),
                        patch.object(gui, 'load_settings', return_value=DEFAULTS.copy()),
                        patch.object(gui.Window, 'send')]
        for item in self.patches:
            item.start()
        self.window = gui.Window()
        self.worker = self.window.process

    def tearDown(self):
        self.window.process = self.worker
        self.window.close()
        for item in reversed(self.patches):
            item.stop()
        self.directory.cleanup()

    def event(self, event):
        self.window.process = Mock()
        self.window.process.readAllStandardOutput.return_value = (json.dumps(event) + '\n').encode()
        self.window.read_events()

    def test_whisper_first_and_output_default(self):
        self.assertEqual(self.window.form.labelForField(self.window.speech_provider).text(), 'Speech provider')
        self.assertEqual(self.window.speech_provider.currentText(), 'Whisper (local)')
        self.assertEqual(self.window.audio_input.currentText(), 'Audio output')
        self.window.audio_input.setCurrentText('Microphone')
        self.assertEqual(self.window.current_settings()['audio_input'], 'Microphone')

    def test_captions_are_plain_text_and_retained(self):
        self.event(dict(type='caption', timestamp='12:00', language='en', text='<b>hello</b>'))
        self.event(dict(type='caption', timestamp='12:01', language='fr', text='Guten Tag'))
        text = self.window.captions.toPlainText()
        self.assertIn('<b>hello</b>', text)
        self.assertIn('Guten Tag', text)
        self.assertLessEqual(self.window.captions.document().blockCount(), self.window.history.value())

    def test_close_waits_for_cleanup_without_blocking_gui(self):
        self.window.process = Mock()
        self.window.process.state.return_value = gui.QProcess.Running
        event = Mock()
        self.window.closeEvent(event)
        event.ignore.assert_called_once()
        self.window.process.write.assert_called_once_with(b'{"action":"stop"}\n')
        self.assertTrue(self.window.closing)

    def test_error_survives_worker_stop(self):
        self.event(dict(type='error', message='Provider unavailable'))
        self.window.finished(0, gui.QProcess.NormalExit)
        self.assertIn('Provider unavailable', self.window.status.text())

    def test_theme_defaults_and_custom_border_transparency(self):
        self.assertEqual(self.window.transparency.value(), -1)
        self.assertEqual(self.window.border_width.value(), -1)
        self.window.transparency.setValue(75)
        self.window.border_width.setValue(6)
        settings = self.window.current_settings()
        self.assertEqual(settings['background_transparency'], 75)
        self.assertEqual(settings['border_width'], 6)
        self.assertIn('border: 6px', self.window.centralWidget().styleSheet())

    def test_suggestion_updates_selected_local_provider_and_model(self):
        self.event(dict(type='suggestion', provider='Ollama', endpoint='http://127.0.0.1:11434',
                        models=['qwen3:4b'], model='qwen3:4b', reason='Suggested model'))
        self.assertEqual(self.window.provider.currentText(), 'Ollama')
        self.assertEqual(self.window.model.currentText(), 'qwen3:4b')

    def test_overlay_has_no_settings_tab_or_translation_controls(self):
        self.assertFalse(self.window.tabs.isTabVisible(1))
        self.assertTrue(self.window.start.isHidden())
        self.assertTrue(self.window.stop.isHidden())
        self.assertTrue(self.window.compact.isHidden())

    def test_ipc_snapshot_never_exposes_token(self):
        self.window.token.setText('private-online-token')
        state = self.window.snapshot()
        self.assertTrue(state['key_ready'])
        self.assertNotIn('private-online-token', json.dumps(state))

    def test_overlay_appearance_change_keeps_unsaved_authentication(self):
        self.window.token.setText('private-online-token')
        self.window.configure({'settings': self.window.current_settings() | {'background_transparency': 60}})
        self.assertEqual(self.window.token.text(), 'private-online-token')
        self.assertEqual(self.window.transparency.value(), 60)

    def test_closing_panel_keeps_visible_overlay_and_capture(self):
        self.window.show()
        self.window.running = True
        with patch.object(self.window, 'close') as close:
            self.window.handle_request({'action': 'release'})
            close.assert_not_called()
        self.assertTrue(self.window.running)

    def test_closing_panel_releases_hidden_controller(self):
        with patch.object(self.window, 'close') as close:
            self.window.handle_request({'action': 'release'})
            close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
