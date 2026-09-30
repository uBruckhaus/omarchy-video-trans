"""Optional Wayland check: captions over fullscreen and isolated to their workspace.
Temporarily opens a blue test window and switches to an unused workspace and back.
No audio capture, inference, credentials, or screenshot storage.
"""
import json,os,sys,tempfile,subprocess
from pathlib import Path
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from PySide6.QtWidgets import QApplication,QMainWindow
from PySide6.QtNetwork import QLocalServer
from PySide6.QtCore import QTimer,QProcess
import gui,bridge
from core import DEFAULTS
app=QApplication([]); app.setQuitOnLastWindowClosed(False)
errors=[]
with tempfile.TemporaryDirectory() as tmp, patch.object(gui,'CONFIG',Path(tmp)),patch.object(gui,'load_settings',return_value=DEFAULTS.copy()),patch.object(gui.Window,'send'),patch.object(bridge,'socket_path',return_value=tmp+'/caption.sock'):
    server=QLocalServer();assert server.listen(tmp+'/caption.sock')
    w=gui.Window(); w.layer_mode=True
    w.captions.setPlainText('VIDEO TRANS FULLSCREEN TEST\nDeutsche Untertitel bleiben über dem Video sichtbar.')
    connections=set()
    def connect():
        c=server.nextPendingConnection();connections.add(c)
        def read():
            if not c.canReadLine():return
            payload=json.loads(bytes(c.readLine()))
            c.write((json.dumps(w.handle_request(payload))+'\n').encode());c.flush();c.disconnectFromServer()
        c.readyRead.connect(read);c.disconnected.connect(lambda:connections.discard(c));read()
    server.newConnection.connect(connect)
    video=QMainWindow();video.setWindowTitle('Video Trans fullscreen test background');video.setStyleSheet('background: #0000ff');video.show()
    def launch():w.show_overlay()
    def check():
        try:
            stderr=bytes(w.layer_process.readAllStandardError()).decode()
            stdout=bytes(w.layer_process.readAllStandardOutput()).decode()
            assert 'ReferenceError' not in stderr + stdout, stderr + stdout
            assert w.layer_process.state()!=QProcess.NotRunning,'Layer process exited'
            layers=json.loads(subprocess.check_output(['hyprctl','layers','-j']))
            matches=[l for m in layers.values() for l in m['levels'].get('3',[]) if l.get('namespace')=='video-trans-captions']
            assert matches, 'Caption overlay was not mapped on layer 3'
            clients=json.loads(subprocess.check_output(['hyprctl','clients','-j']))
            background=next(c for c in clients if c['title']==video.windowTitle())
            assert background['fullscreen']>0,background
            state=subprocess.check_output(['quickshell','ipc','-p',str(ROOT / 'overlay/shell.qml'),'call','video-trans-overlay','state'],text=True)
            print('Fullscreen layer state:',state)
            assert json.loads(state)['visible']
            print('Fullscreen background + overlay layer verified')
            ids={c['id'] for c in json.loads(subprocess.check_output(['hyprctl','workspaces','-j']))}
            root_id=json.loads(state)['workspace']
            other=next(n for n in range(90,110) if n not in ids)
            subprocess.run(['hyprctl','eval','hl.dispatch(hl.dsp.focus({workspace="'+str(other)+'"}))'],check=True,stdout=subprocess.DEVNULL)
            QTimer.singleShot(500,lambda: check_away(root_id))
        except Exception as e:errors.append(e)
        if errors:
            w.close();video.close();QTimer.singleShot(500,app.quit)
    def state():
        return json.loads(subprocess.check_output(['quickshell','ipc','-p',str(ROOT / 'overlay/shell.qml'),'call','video-trans-overlay','state'],text=True))
    def check_away(original):
        try:
            assert not state()['visible'],'Overlay followed to another workspace'
            print('Overlay hidden on other workspace')
        except Exception as e:errors.append(e)
        subprocess.run(['hyprctl','eval','hl.dispatch(hl.dsp.focus({workspace="'+str(original)+'"}))'],check=True,stdout=subprocess.DEVNULL)
        QTimer.singleShot(500,check_return)
    def check_return():
        try:
            assert state()['visible'],'Overlay did not return with original workspace'
            print('Overlay visible again on starting workspace')
        except Exception as e:errors.append(e)
        w.close();video.close();QTimer.singleShot(500,app.quit)
    QTimer.singleShot(400,launch);QTimer.singleShot(1000,video.showFullScreen);QTimer.singleShot(2600,check);QTimer.singleShot(7000,app.quit)
    app.exec()
if errors:raise errors[0]
