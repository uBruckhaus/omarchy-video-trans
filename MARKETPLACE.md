# Marketplace submission draft

**Name:** Video Trans

**ID:** `ubruckhaus.video-trans`

**Repository:** https://github.com/uBruckhaus/omarchy-video-trans

**Category:** Media

**Tags:** ai, media, bar, quickshell, captions, translation, whisper

**Screenshot:** `preview.png` (synthetic captions)

Live translated captions from audio output or an explicitly selected microphone. A native Omarchy panel controls translation; the independent caption overlay is resizable and floating. Local Whisper automatically detects speech language and filters non-speech. Choose llama.cpp, Ollama or an OpenAI-compatible online translator and model, with an automatic local-model suggestion based on your target language. Overlay-only transparency and border controls, persistent scrollback and cleanup on Stop/Close. German target by default.

## Capabilities

- Reads PulseAudio/PipeWire sink/source metadata and captures the explicitly selected device using FFmpeg. Microphone capture is opt-in through the input selector.
- Processes speech locally with faster-whisper and Silero VAD.
- Sends recognized text to the chosen local or remote translation endpoint; audio is never uploaded.
- Starts/stops owned llama.cpp/Ollama user services or an owned Ollama child process; unloads newly used models.
- Stores preferences and optional owner-only plaintext bearer credentials in the user's XDG config directory.
- Downloads Python dependencies only via explicit setup; Whisper downloads the selected model on first Start. No telemetry, recorded audio or disk transcript history.

## Dependencies

Omarchy shell with plugin support, PipeWire-Pulse, `ffmpeg`, `pactl` (`libpulse`) and `uv`. Setup installs Python 3.12, PySide6, faster-whisper and httpx in an isolated runtime. Local translation requires a configured llama.cpp router or Ollama with downloaded text models. Online translation requires an OpenAI-compatible endpoint/account.

## Submission

Validate the manifest, run tests and review screenshot/README, then submit the repository through https://plugins.omarchy.org/publish.html. This file is a submission draft; publishing the GitHub repository does not create a marketplace listing.
