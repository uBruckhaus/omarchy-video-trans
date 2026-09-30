"""Render synthetic gallery images without capture, inference or credentials."""
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['QT_QPA_PLATFORMTHEME'] = 'none'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
import gui
from core import DEFAULTS

root = Path(__file__).resolve().parents[1]
app = QApplication([])
app.setStyle('Fusion')
with tempfile.TemporaryDirectory() as directory, patch.object(gui, 'CONFIG', Path(directory)), \
     patch.object(gui, 'load_settings', return_value=DEFAULTS.copy()), patch.object(gui.Window, 'send'):
    window = gui.Window()
    window.captions.setPlainText(
        '12:00:05 · en → German\n'
        'Guten Morgen. Heute sehen wir uns an, wie Solarmodule Sonnenlicht in Strom umwandeln.\n\n'
        '12:00:10 · en → German\n'
        'Diese Untertitel bleiben sichtbar. Sie können zurückscrollen und in Ihrem eigenen Tempo lesen.')
    window.model.setCurrentText('Local multilingual model')
    window.status.setText('Video Trans · example captions · no recording or inference')
    window.show()
    app.processEvents()
    window.grab().save(str(root / 'preview.png'))
    window.transparency.setValue(60)
    app.processEvents()
    alpha = window.grab().toImage().pixelColor(450, 400).alpha()
    assert alpha < 255, f'Background is unexpectedly opaque: alpha={alpha}'
    print(f'Gallery previews rendered; background alpha={alpha}, text remains opaque.')
    window.close()
