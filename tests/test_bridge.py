from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bridge
import core


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.config = patch.object(core, 'CONFIG', Path(self.directory.name))
        self.config.start()
        self.offline = patch.object(bridge, 'offline_state', return_value=dict(status='Ready'))
        self.offline.start()

    def tearDown(self):
        self.offline.stop()
        self.config.stop()
        self.directory.cleanup()

    def test_lifecycle_actions_reach_controller(self):
        with patch.object(bridge, 'send', return_value=dict(status='Listening')) as send:
            for name in ('toggle', 'start', 'stop', 'show', 'clear', 'download', 'cancel-download', 'models', 'suggest'):
                bridge.command([name])
                send.assert_called_with(dict(action=name))
            bridge.command(['status'])
            send.assert_called_with(dict(action='state'))

    def test_offline_actions_never_start_controller(self):
        with patch.object(bridge, 'request', side_effect=FileNotFoundError), patch.object(bridge.subprocess, 'Popen') as popen:
            for name in ('stop', 'clear', 'cancel-download', 'status'):
                bridge.command([name])
        popen.assert_not_called()

    def test_settings_saved_without_running_controller(self):
        with patch.object(bridge, 'request', side_effect=FileNotFoundError):
            bridge.command(['target', 'french'])
            bridge.command(['input', 'microphone'])
            bridge.command(['follow', 'off'])
        settings = core.load_settings()
        self.assertEqual((settings['target'], settings['audio_input'], settings['auto_scroll']),
                         ('French', 'Microphone', False))

    def test_text_color_toggles_and_validates(self):
        for current, expected in (('black', 'white'), ('white', 'black'), ('theme', 'black')):
            with patch.object(bridge, 'send', return_value=dict(settings=dict(text_color=current))), \
                 patch.object(bridge, 'change_setting', return_value={}) as change:
                bridge.command(['text-color'])
            change.assert_called_once_with('text_color', expected)
        with patch.object(bridge, 'request', side_effect=FileNotFoundError):
            bridge.command(['text-color', 'white'])
        self.assertEqual(core.load_settings()['text_color'], 'white')
        with self.assertRaises(ValueError):
            bridge.command(['text-color', 'red'])

    def test_font_steps_and_clamps(self):
        for current, word, expected in ((24, 'bigger', 28), (24, 'smaller', 20), (62, 'bigger', 64), (14, 'smaller', 12)):
            with patch.object(bridge, 'send', return_value=dict(settings=dict(font_size=current))), \
                 patch.object(bridge, 'change_setting', return_value={}) as change:
                bridge.command(['font', word])
            change.assert_called_once_with('font_size', expected)
        with patch.object(bridge, 'change_setting', return_value={}) as change:
            bridge.command(['font', '99'])
        change.assert_called_once_with('font_size', 64)
        for bad in ('huge', '-4', '1e3', ''):
            with self.assertRaises(ValueError):
                bridge.command(['font', bad] if bad else ['font'])

    def test_font_saved_without_running_controller(self):
        with patch.object(bridge, 'request', side_effect=FileNotFoundError):
            bridge.command(['font', 'bigger'])
        self.assertEqual(core.load_settings()['font_size'], core.DEFAULTS['font_size'] + 4)

    def test_follow_toggles_current_value(self):
        with patch.object(bridge, 'send', return_value=dict(settings=dict(auto_scroll=True))), \
             patch.object(bridge, 'change_setting', return_value={}) as change:
            bridge.command(['follow'])
        change.assert_called_once_with('auto_scroll', False)

    def test_refused_change_while_translating_is_an_error(self):
        with patch.object(bridge, 'request', return_value=dict(running=True, settings=dict(target='German'))):
            result = bridge.command(['target', 'French'])
        self.assertIn('stop captions', result['error'])

    def test_rejects_unknown_actions_and_values(self):
        for argv in (['dance'], ['target', 'Klingon'], ['input', 'Line in'], ['follow', 'maybe'], ['stop', 'now']):
            with self.assertRaises(ValueError):
                bridge.command(argv)

    def test_settings_opens_popup_through_argv(self):
        with patch.object(bridge.subprocess, 'Popen') as popen:
            bridge.command(['settings'])
        self.assertEqual(popen.call_args.args[0], ['omarchy-shell', 'shell', 'toggle', 'ubruckhaus.video-trans', '{}'])

    def test_cli_exit_codes(self):
        with patch('builtins.print'):
            self.assertEqual(bridge.cli(['help']), 0)
            self.assertEqual(bridge.cli(['dance']), 2)
            with patch.object(bridge, 'send', return_value=dict(error='Video Trans: failed')):
                self.assertEqual(bridge.cli(['start']), 1)


if __name__ == '__main__':
    unittest.main()
