# Video Trans · Marketplace description

**Name:** Video Trans

**ID:** `ubruckhaus.video-trans`

**Repository:** https://github.com/uBruckhaus/omarchy-video-trans

**Category:** Productivity

**Tags:** ai, media, bar

**Screenshot:** `preview.png` (real 0.4.0 screenshots: synthesized narration over a generated test video)

Live translated captions over any video, call or microphone: local Whisper, llama.cpp, Ollama or online translation. Guided setup, shortcut actions, black or white text.

Speech is recognized locally by Whisper and translated by llama.cpp, Ollama or an OpenAI-compatible online API. Captions float above fullscreen video in a movable, resizable window with white or black text, adjustable size and duration. A guided popup names the one next setup step and fixes it with one click. Every action (start, stop, show, clear, text colour, target language, input) is a `video-trans` command, a desktop action and a tray entry, so Launch & Bind can put it on a key. The bar icon turns the theme's green while captions run.

## Capabilities

- Reads PulseAudio/PipeWire sink/source metadata and captures the explicitly selected device using FFmpeg. Microphone capture is opt-in through the input selector.
- Processes speech locally with faster-whisper and Silero VAD.
- Sends recognized text to the chosen local or remote translation endpoint; audio is never uploaded.
- Starts/stops owned llama.cpp/Ollama user services or an owned Ollama child process; unloads newly used models.
- Stores preferences and optional owner-only plaintext bearer credentials in the user's XDG config directory.
- Downloads Python dependencies only via explicit setup (popup **Set up now** or `setup.sh`); Whisper downloads the selected model on request or first Start. No telemetry, recorded audio or disk transcript history.
- Guided setup installs missing system packages (`ffmpeg`, `libpulse`, `quickshell`, `uv`) through the system's graphical authentication prompt, only after the user presses **Set up now**.
- Adds a managed `~/.local/bin/video-trans` command and `~/.local/share/applications/video-trans.desktop` (desktop actions for shortcuts) from setup or the **Add shortcut actions** button; files it did not create are never replaced.
- Runs a small tray process (`tray.py`) while the bar widget is loaded; its entries run `video-trans <action>`.

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
