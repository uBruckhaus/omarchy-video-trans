import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['QT_QPA_PLATFORMTHEME'] = 'none'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
import tray
from core import DEFAULTS

APP = QApplication.instance() or QApplication([])


class TrayTests(unittest.TestCase):
    def setUp(self):
        self.runtime = tempfile.TemporaryDirectory()
        self.patches = [patch.dict(os.environ, XDG_RUNTIME_DIR=self.runtime.name),
                        patch.object(tray, 'load_settings', return_value=DEFAULTS | dict(target='French', auto_scroll=False))]
        for item in self.patches:
            item.start()
        self.tray = tray.Tray()

    def tearDown(self):
        self.tray.timer.stop()
        for item in reversed(self.patches):
            item.stop()
        self.runtime.cleanup()

    def labels(self, menu):
        return [action.text() for action in menu.actions() if not action.isSeparator() and not action.text().startswith('Status')]

    def test_menu_offers_every_action_with_fixed_labels(self):
        labels = self.labels(self.tray.menu)
        for label in ('Start / stop captions', 'Start captions', 'Stop captions', 'Show captions', 'Clear captions',
                      'Follow new captions', 'Caption text', 'Larger caption text', 'Smaller caption text', 'Translate to', 'Audio input', 'Download Whisper model',
                      'Auto-select local model', 'Refresh models', 'Settings…'):
            self.assertIn(label, labels)
        self.tray.state = dict(running=True, settings=DEFAULTS, status='Listening')
        self.tray.refresh()
        self.assertEqual(labels, self.labels(self.tray.menu))
        self.assertTrue(all(a.isEnabled() for a in self.tray.menu.actions() if not a.text().startswith('Status')))

    def test_entries_run_video_trans_commands(self):
        with patch.object(self.tray, 'run') as run:
            self.tray.target_actions['Spanish'].trigger()
            self.tray.input_actions['Microphone'].trigger()
            next(a for a in self.tray.menu.actions() if a.text() == 'Start captions').trigger()
            self.tray.follow_action.trigger()
        run.assert_any_call('target', 'Spanish')
        run.assert_any_call('input', 'Microphone')
        run.assert_any_call('start')
        run.assert_any_call('follow', 'on')

    def test_font_entries(self):
        with patch.object(self.tray, 'run') as run:
            for label in ('Larger caption text', 'Smaller caption text'):
                next(a for a in self.tray.menu.actions() if a.text() == label).trigger()
        run.assert_any_call('font', 'bigger')
        run.assert_any_call('font', 'smaller')

    def test_caption_text_submenu(self):
        with patch.object(self.tray, 'run') as run:
            self.tray.color_actions['Black'].trigger()
        run.assert_called_once_with('text-color', 'black')
        self.tray.state = dict(running=True, settings=DEFAULTS | dict(text_color='white'))
        self.tray.refresh()
        self.assertTrue(self.tray.color_actions['White'].isChecked())

    def test_off_state_comes_from_settings_file(self):
        self.tray.disconnected()
        self.assertFalse(self.tray.running)
        self.assertTrue(self.tray.target_actions['French'].isChecked())
        self.assertFalse(self.tray.follow_action.isChecked())

    def test_running_state_from_controller(self):
        self.tray.state = dict(running=True, settings=DEFAULTS | dict(target='Korean'), status='Listening')
        self.tray.refresh()
        self.assertTrue(self.tray.running)
        self.assertTrue(self.tray.target_actions['Korean'].isChecked())
        self.assertIn('translating', self.tray.toolTip())

    def test_markup_never_reaches_notifications_or_tooltips(self):
        hostile = 'Bad <img src="http://x/y.png"> &amp;\r\n\x1b[31m'
        cleaned = tray.plain(hostile)
        self.assertFalse(set('<>&\r\n\x1b') & set(cleaned))
        self.assertLessEqual(len(tray.plain('x' * 1000)), 300)
        self.tray.state = dict(running=False, status=hostile, settings=DEFAULTS)
        self.tray.refresh()
        self.assertNotIn('<', self.tray.toolTip())
        self.assertNotIn('<', self.tray.status_action.text())

    def test_run_uses_bridge_with_argv(self):
        with patch.object(tray.QProcess, 'start') as start:
            self.tray.run('target', 'German')
        start.assert_called_once_with('bash', [str(tray.ROOT / 'bridge.sh'), 'target', 'German'])


if __name__ == '__main__':
    unittest.main()
