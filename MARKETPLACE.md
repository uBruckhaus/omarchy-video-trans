# Video Trans · Marketplace description

**Name:** Video Trans

**ID:** `ubruckhaus.video-trans`

**Repository:** https://github.com/uBruckhaus/omarchy-video-trans

**Category:** Productivity

**Tags:** ai, media, bar

**Screenshot:** `preview.png` (synthetic captions)

Live translated captions from audio output or an explicitly selected microphone. A native Omarchy panel controls translation; the independent caption overlay is resizable and floating above fullscreen video, restricted to its starting workspace. Local Whisper automatically detects speech language and filters non-speech. Choose llama.cpp, Ollama or an OpenAI-compatible online translator and model, with an automatic local-model suggestion based on your target language. Overlay-only transparency and border controls, adjustable caption duration and scrollback and cleanup on Stop/Close. German target by default. Startup checks display green/red checkmarks for speech recognition, audio capture, translator and model availability.

## Capabilities

- Reads PulseAudio/PipeWire sink/source metadata and captures the explicitly selected device using FFmpeg. Microphone capture is opt-in through the input selector.
- Processes speech locally with faster-whisper and Silero VAD.
- Sends recognized text to the chosen local or remote translation endpoint; audio is never uploaded.
- Starts/stops owned llama.cpp/Ollama user services or an owned Ollama child process; unloads newly used models.
- Stores preferences and optional owner-only plaintext bearer credentials in the user's XDG config directory.
- Downloads Python dependencies only via explicit setup; Whisper downloads the selected model on first Start. No telemetry, recorded audio or disk transcript history.

## Dependencies

Omarchy shell with plugin support, PipeWire-Pulse, `ffmpeg`, `pactl` (`libpulse`) and `uv`. Setup installs Python 3.12, PySide6, faster-whisper and httpx in an isolated runtime. Local translation requires a configured llama.cpp router or Ollama with downloaded text models. Online translation requires an OpenAI-compatible endpoint/account.

## Installation

```bash
omarchy pkg add ffmpeg libpulse uv
omarchy plugin add https://github.com/uBruckhaus/omarchy-video-trans.git --enable
bash ~/.config/omarchy/plugins/ubruckhaus.video-trans/setup.sh
```

Explicit runtime setup is required after adding the plugin. Omarchy does not execute setup hooks. See the [user manual](MANUAL.md) for first-session guidance, troubleshooting and removal.

## Publication

Marketplace submission targets Productivity with the tags ai, media and bar. A maintainer must review the exact submitted commit before the listing is published. Installer, dependency management and user-service management may require baseline review; these capabilities are documented above. MIT licensed; the preview contains synthetic example captions.
