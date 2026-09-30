"""Disposable worker process. Models never live in the GUI or Omarchy shell."""
import json
import importlib.util
import queue
import shutil
import signal
import subprocess
import sys
import threading
import time

from core import Provider, LANGUAGES, capture_command, audio_devices, local_provider_choice, suggest_model


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

    def check(self, key, label, status, detail):
        emit('check', id=key, label=label, status=status, detail=detail)

    def quick_check(self, command):
        settings = command['settings']
        errors = []
        target_ok = settings['target'] in LANGUAGES
        self.check('target', 'Target language', 'ok' if target_ok else 'error', settings['target'])
        if not target_ok:
            errors.append('Select a supported target language.')
        try:
            if not shutil.which('ffmpeg') or not shutil.which('pactl'):
                raise ValueError('Install ffmpeg and libpulse before starting.')
            capture_command(settings['output'], settings['noise_filter'], settings.get('audio_input', 'Audio output'))
            self.check('audio', 'Audio capture', 'ok', settings.get('audio_input', 'Audio output') + ' device available')
        except (ValueError, subprocess.SubprocessError, OSError) as exc:
            self.check('audio', 'Audio capture', 'error', str(exc))
            errors.append('Audio capture is unavailable.')
        whisper_ok = all(importlib.util.find_spec(name) is not None for name in ('faster_whisper', 'numpy', 'av'))
        source_ok = not (settings['speech_model'].endswith('.en') and settings['source'] != 'en')
        if not whisper_ok or not source_ok:
            detail = 'Run setup.sh to install Whisper.' if not whisper_ok else 'Choose a multilingual Whisper model for automatic language detection, or set the source to en.'
            self.check('whisper', 'Whisper', 'error', detail)
            errors.append(detail)
        else:
            self.check('whisper', 'Whisper', 'checking', settings['speech_model'] + ' · checking/loading speech model')
        if errors:
            raise ValueError(' '.join(errors))
        try:
            self.configure(command)
            previous_timeout = self.provider.client.timeout
            import httpx
            self.provider.client.timeout = httpx.Timeout(5)
            try:
                models = self.provider.models()
            finally:
                self.provider.client.timeout = previous_timeout
            self.check('provider', 'Translation provider', 'ok', settings['provider'] + ' · reachable')
        except Exception as exc:
            status_code = getattr(getattr(exc, 'response', None), 'status_code', None)
            if settings['provider'] == 'Online' and status_code in (404, 405, 501):
                self.check('provider', 'Translation provider', 'checking', 'Online endpoint configured; verified by the first translation')
                self.check('model', 'Translation model', 'checking', settings['model'] + ' · verified by the first translation')
                if not settings['model']:
                    raise ValueError('Select an online translation model.')
                return
            detail = str(exc) if isinstance(exc, (ValueError, RuntimeError)) else ('Authentication failed; check your API key or bearer token.' if status_code in (401, 403) else 'Provider is unavailable; check its endpoint and service.')
            self.check('provider', 'Translation provider', 'error', detail)
            self.check('model', 'Translation model', 'error', 'Could not verify the configured model')
            raise ValueError(detail) from None
        if settings['model'] not in models:
            self.check('model', 'Translation model', 'error', settings['model'] + ' · not available from this provider')
            raise ValueError('The selected translation model is unavailable. Refresh models or use Auto-select local.')
        self.check('model', 'Translation model', 'ok', settings['model'])

    def download_speech(self, settings):
        emit('status', message='Downloading/checking Whisper ' + settings['speech_model'] + '…')
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
            self.check('whisper', 'Whisper', 'error', 'Speech model download/load failed')
            raise RuntimeError('Speech model download/load failed. Check internet access, disk space or the model name.')
        self.download = None
        self.check('whisper', 'Whisper', 'ok', settings['speech_model'] + ' · downloaded and ready')

    def run_capture(self, settings):
        import numpy as np
        from faster_whisper import WhisperModel
        if not settings['model']:
            raise ValueError('Select a translation model before starting.')
        emit('status', message='Loading speech model (first use downloads it)…')
        self.download_speech(settings)
        if self.stop.is_set():
            return
        # CPU int8 leaves the local GPU available to llama.cpp / Ollama.
        self.speech = WhisperModel(settings['speech_model'], device='cpu', compute_type='int8', cpu_threads=4, local_files_only=True)
        self.check('whisper', 'Whisper', 'ok', settings['speech_model'] + ' · ready')
        if self.stop.is_set():
            return
        emit('status', message='Speech model ready · connecting to the translation provider…')
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
        emit('started')
        emit('status', message='Listening to ' + settings.get('audio_input', 'Audio output').lower() + '…')
        previous = ''
        silent_seconds = 0
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
                silent_seconds += len(audio) / 16000
                if silent_seconds >= 10:
                    emit('status', message='No audio on the selected device. Select the output your video is playing through, and check that playback is unmuted.')
                    silent_seconds = 0
                continue
            silent_seconds = 0
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
                if not text:
                    emit('status', message='Audio received · no clear speech detected yet. Check the source-language setting or use auto.')
                continue
            previous = text
            emit('status', message=f'Detected {info.language} ({info.language_probability:.0%}) · translating…')
            translated = self.provider.translate(text, info.language)
            if self.provider.kind == 'Online':
                self.check('provider', 'Translation provider', 'ok', 'Online · translation request succeeded')
                self.check('model', 'Translation model', 'ok', settings['model'])
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
                elif action == 'download':
                    self.download_speech(command['settings'])
                    if self.stop.is_set():
                        self.cleanup()
                        emit('stopped')
                        return
                    emit('downloaded', model=command['settings']['speech_model'])
                elif action == 'start':
                    emit('status', message='Checking startup requirements…')
                    self.quick_check(command)
                    settings = command['settings']
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
                if action in ('start', 'models', 'suggest', 'download'):
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
