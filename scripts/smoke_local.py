"""Optional real local integration check using an inaudible temporary Pulse sink.

python scripts/smoke_local.py --fixture /path/to/speech.wav --model router-model-id
Requires pactl, paplay and an already cached Whisper small model.
"""
import argparse
import json
from pathlib import Path
import selectors
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import DEFAULTS


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--fixture', required=True)
    parser.add_argument('--model', required=True)
    args = parser.parse_args()
    sink = 'video_trans_smoke_' + str(int(time.time()))
    module = subprocess.check_output(['pactl', 'load-module', 'module-null-sink', 'sink_name=' + sink], text=True).strip()
    process = player = None
    selector = selectors.DefaultSelector()
    saw_caption = False
    try:
        settings = DEFAULTS | dict(model=args.model, output=sink + '.monitor')
        process = subprocess.Popen([sys.executable, '-u', str(Path(__file__).resolve().parents[1] / 'backend.py')],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        process.stdin.write(json.dumps(dict(action='start', settings=settings)) + '\n')
        process.stdin.flush()
        selector.register(process.stdout, selectors.EVENT_READ)
        deadline = time.monotonic() + 100
        while time.monotonic() < deadline:
            if not selector.select(timeout=0.5):
                if process.poll() is not None:
                    break
                continue
            line = process.stdout.readline()
            if not line:
                break
            event = json.loads(line)
            print(event, flush=True)
            if event['type'] == 'error':
                raise RuntimeError(event['message'])
            if event['type'] == 'status' and event['message'].startswith('Listening') and player is None:
                player = subprocess.Popen(['paplay', '--device=' + sink, args.fixture])
            if event['type'] == 'caption':
                saw_caption = True
                break
        if not saw_caption:
            raise RuntimeError('No translated caption received within timeout')
    finally:
        if player:
            if player.poll() is None:
                player.terminate()
            player.wait(timeout=5)
        if process:
            if process.poll() is None:
                process.stdin.write('{"action":"stop"}\n')
                process.stdin.flush()
            process.wait(timeout=100)
            if process.returncode:
                raise RuntimeError('Backend exited unsuccessfully')
        selector.close()
        subprocess.run(['pactl', 'unload-module', module], check=True, timeout=5)
    print('End-to-end output capture → Whisper detection → German translation → cleanup: OK')


if __name__ == '__main__':
    main()
