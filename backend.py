"""Disposable worker process. Models never live in the GUI or Omarchy shell."""
import json
import queue
import signal
import subprocess
import sys
import threading
import time

from core import Provider, capture_command, audio_devices, local_provider_choice, suggest_model


def emit(kind, **values):
    print(json.dumps(dict(type=kind, **values)), flush=True)


class Backend:
    def __init__(self):
        self.stop = threading.Event()
        self.jobs = queue.Queue()
        self.capture = None
        self.download = None
        self.provider = None
        self.speech = None
        self.quitting = False

    def cancel(self):
        self.stop.set()
        proc = self.capture
        if proc and proc.poll() is None:
            proc.terminate()
        if self.download and self.download.poll() is None:
            self.download.terminate()

    def cleanup(self):
        self.cancel()
        if self.download:
            try:
                self.download.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.download.kill()
                self.download.wait()
            self.download = None
        if self.capture:
            try:
                self.capture.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.capture.kill()
                self.capture.wait()
            self.capture = None
        # A separate worker process exits on Stop, releasing all CTranslate2 allocations.
        self.speech = None
        if self.provider:
            try:
                errors = self.provider.close()
                if errors:
                    emit('error', message='; '.join(errors))
            except Exception as exc:
                emit('error', message=f'Provider cleanup failed: {type(exc).__name__}')
            self.provider = None

    def configure(self, command):
        settings = command['settings']
        signature = (settings['provider'], settings['endpoint'], command.get('token', ''))
        if self.provider and signature != self.signature:
            self.cleanup()
            self.stop.clear()
        if not self.provider:
            self.signature = signature
            self.provider = Provider(settings, command.get('token', ''), self.stop)
        else:
            self.provider.settings = settings
        return settings

    def run_capture(self, settings):
        import numpy as np
        from faster_whisper import WhisperModel
        if not settings['model']:
            raise ValueError('Select a translation model before starting.')
        emit('status', message='Loading speech model (first use downloads it)…')
        # Downloads are cancellable children; closing during first-run setup must
        # not leave a network download or a provider service alive.
        self.download = subprocess.Popen([
            sys.executable, '-c',
            'from faster_whisper import WhisperModel\nimport sys\n'
            'try:\n WhisperModel(sys.argv[1], device="cpu", compute_type="int8", cpu_threads=4, local_files_only=True)\n'
            'except Exception:\n WhisperModel(sys.argv[1], device="cpu", compute_type="int8", cpu_threads=4)\n',
            settings['speech_model']], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        while self.download.poll() is None:
            if self.stop.wait(0.2):
                return
        if self.download.returncode:
            raise RuntimeError('Speech model download/load failed. Check internet access, disk space or the model name.')
        self.download = None
        # CPU int8 leaves the local GPU available to llama.cpp / Ollama.
        self.speech = WhisperModel(settings['speech_model'], device='cpu', compute_type='int8', cpu_threads=4, local_files_only=True)
        if self.stop.is_set():
            return
        self.provider.ensure_service()
        command = capture_command(settings['output'], settings['noise_filter'], settings.get('audio_input', 'Audio output'))
        self.capture = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        frames = queue.Queue(maxsize=6)
        chunk_bytes = int(settings['chunk_seconds']) * 16000 * 2

        def reader():
            while not self.stop.is_set():
                data = bytearray()
                while len(data) < chunk_bytes and not self.stop.is_set():
                    part = self.capture.stdout.read(chunk_bytes - len(data))
                    if not part:
                        break
                    data.extend(part)
                if not data:
                    break
                if len(data) % 2:
                    data = data[:-1]
                if frames.full():
                    try:
                        frames.get_nowait()
                    except queue.Empty:
                        pass
                    emit('status', message='Translation is behind playback; skipping oldest audio chunk.')
                frames.put(bytes(data))
            try:
                frames.put_nowait(None)
            except queue.Full:
                pass

        capture_thread = threading.Thread(target=reader, daemon=True)
        capture_thread.start()
        emit('status', message='Listening to ' + settings.get('audio_input', 'Audio output').lower() + '…')
        previous = ''
        tail = np.zeros(0, dtype=np.float32)
        while not self.stop.is_set():
            try:
                data = frames.get(timeout=0.25)
            except queue.Empty:
                if not capture_thread.is_alive():
                    raise RuntimeError('Playback capture ended. Check the selected output device.')
                continue
            if data is None:
                raise RuntimeError('Playback capture ended. Check the selected output device.')
            audio = np.frombuffer(data, dtype='<i2').astype(np.float32) / 32768.0
            if not len(audio) or float(np.sqrt(np.mean(audio * audio))) < 0.002:
                tail = np.zeros(0, dtype=np.float32)
                continue
            overlap = len(tail) / 16000
            combined = np.concatenate((tail, audio))
            tail = audio[-12800:]
            segments, info = self.speech.transcribe(
                combined, language=None if settings['source'] == 'auto' else settings['source'],
                vad_filter=True, vad_parameters={'min_silence_duration_ms': 300, 'speech_pad_ms': 200},
                condition_on_previous_text=False, beam_size=3, temperature=0,
                no_speech_threshold=0.6, log_prob_threshold=-1.0, compression_ratio_threshold=2.4)
            segments = [s for s in segments if s.end > overlap and s.no_speech_prob < 0.6 and s.avg_logprob > -1.0]
            text = ' '.join(s.text.strip() for s in segments).strip()
            if self.stop.is_set():
                break
            if not text or text == previous:
                continue
            previous = text
            emit('status', message=f'Detected {info.language} ({info.language_probability:.0%}) · translating…')
            translated = self.provider.translate(text, info.language)
            if not self.stop.is_set():
                emit('caption', source=text, language=info.language, text=translated, timestamp=time.strftime('%H:%M:%S'))

    def work(self):
        while True:
            command = self.jobs.get()
            action = command.get('action')
            if action in ('stop', 'quit'):
                self.cleanup()
                emit('stopped')
                # Exit, including on Stop, to actually free speech-model memory.
                return
            if self.stop.is_set():
                self.cleanup()
                emit('stopped')
                return
            try:
                if action == 'outputs':
                    emit('outputs', outputs=audio_devices(command.get('settings', {}).get('audio_input', 'Audio output')))
                elif action == 'models':
                    self.configure(command)
                    emit('models', models=self.provider.models())
                    emit('status', message='Provider ready. Select a model and press Start.')
                elif action == 'suggest':
                    settings = command['settings'].copy()
                    selected = local_provider_choice(settings['provider'])
                    if selected != settings['provider']:
                        settings.update(provider=selected, endpoint='http://127.0.0.1:8080' if selected == 'llama.cpp' else 'http://127.0.0.1:11434')
                    token = command.get('token', '') if selected == command['settings']['provider'] else ''
                    self.configure(command | {'settings': settings, 'token': token})
                    models = self.provider.models()
                    model, reason = suggest_model(models, settings['target'])
                    emit('suggestion', models=models, model=model, provider=selected, endpoint=settings['endpoint'], reason=reason)
                elif action == 'start':
                    settings = self.configure(command)
                    self.run_capture(settings)
                    self.cleanup()
                    emit('stopped')
                    return
            except InterruptedError:
                self.cleanup()
                emit('stopped')
                return
            except Exception as exc:
                # Never expose provider response bodies or Authorization headers.
                message = str(exc) if isinstance(exc, (ValueError, RuntimeError, FileNotFoundError)) else type(exc).__name__
                emit('error', message=message)
                if action in ('start', 'models', 'suggest'):
                    self.cleanup()
                    emit('stopped')
                    return

    def run(self):
        worker = threading.Thread(target=self.work)
        worker.start()
        def termination(signum, frame):
            self.cancel()
            self.jobs.put({'action': 'quit'})
        signal.signal(signal.SIGTERM, termination)
        signal.signal(signal.SIGINT, termination)
        # Reader daemon cannot keep an already stopped worker/process alive.
        def commands():
            for line in sys.stdin:
                try:
                    command = json.loads(line)
                    if command.get('action') in ('stop', 'quit'):
                        self.cancel()
                    self.jobs.put(command)
                except (ValueError, TypeError):
                    emit('error', message='Invalid backend command')
            self.cancel()
            self.jobs.put({'action': 'quit'})
        threading.Thread(target=commands, daemon=True).start()
        worker.join()


if __name__ == '__main__':
    Backend().run()
