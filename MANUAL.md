# Video Trans · User manual

**Live translated captions for videos, calls and other desktop audio on Omarchy.**

Video Trans recognizes speech locally with Whisper, translates it with your chosen provider, and displays captions in a movable window above fullscreen video. German is the initial target language. The bar popup controls the session; the caption window stays independent.

[Install](#install) · [First session](#your-first-session) · [Controls](#caption-controls) · [Troubleshooting](#troubleshooting) · [Remove](#remove-and-clean-up)

## Install

Use an Omarchy version with shell plugin support, running PipeWire-Pulse. In a terminal:

```bash
omarchy pkg add ffmpeg libpulse uv
omarchy plugin add https://github.com/uBruckhaus/omarchy-video-trans.git --enable
bash ~/.config/omarchy/plugins/ubruckhaus.video-trans/setup.sh
```

The plugin command adds the bar widget. **Setup is a separate required step:** Omarchy does not run setup scripts automatically. Setup creates an isolated Python 3.12 environment with pinned PySide6, faster-whisper and httpx dependencies. It does not install a translator, change your keybindings, or replace your settings. Internet access is needed for setup and uncached speech models.

Choose one translation backend before starting:

| Provider | What you need | Default endpoint |
| --- | --- | --- |
| llama.cpp | An existing user `llama-server.service`, router and text models | `http://127.0.0.1:8080` |
| Ollama | An existing Ollama installation and a downloaded text model | `http://127.0.0.1:11434` |
| Online | An OpenAI-compatible API, model and API key or bearer token | Your provider's HTTPS URL |

Whisper is the speech recognizer, not the translation provider. Video Trans does not download translation models. Local translation setup and shared-service behavior are documented in the [README](README.md#providers-and-authentication).

## Your first session

1. Start playback, then click the Video Trans bar icon.
2. Choose **Audio output** and the device playing your video. This captures all applications using that output. For microphone speech, explicitly select **Microphone** and its device instead.
3. Leave the source language on **auto**, choose your target language and a multilingual Whisper model. Smaller models need fewer resources; larger models can take longer. CPU/int8 recognition keeps GPU memory available for translation.
4. Optionally click **Download selected Whisper model** before the session. It only downloads speech recognition data. You can cancel it. Otherwise the first Start downloads the model when necessary.
5. Choose llama.cpp, Ollama or Online. Use **Refresh models** and select an installed text model. **Auto-select local** suggests a model for the target language; review the suggestion. From Online it may switch to a detected local backend. It does not download or benchmark translation models.
6. For Online, expand **Provider and recognition settings**, enter your endpoint and model, enter your token, and click **Apply token**. Enable **Save token locally** only if you want it retained between sessions.
7. Click **Start**. Check the startup indicators for audio, recognition and translation readiness. Gray means pending, green means ready, and red explains a blocking problem. Captions appear once speech is recognized and translated.

Closing the popup leaves translation running when the caption window is visible. **Stop** and **Close overlay** stop capture and release owned resources. Changing the input or speech model is easiest after stopping the session.

## Caption controls

| Control | Effect |
| --- | --- |
| Drag with the left mouse button | Move the caption window |
| Drag the bottom-right handle | Resize the caption window |
| Shift + drag | Select caption text |
| Mouse wheel | Read earlier captions |
| Follow new captions | Automatically scroll to newly received captions |
| Caption duration | Keep each caption visible for 1–120 seconds; default 5 |
| Caption font size | Change readability, including during translation |
| Show captions | Open the caption window without starting capture |
| Clear captions | Remove the retained text |
| Stop / Close overlay | Close the caption window and end the session |

The caption overlay remains above fullscreen video on Wayland and belongs to the workspace where it opened. Switching workspaces hides it while capture continues; returning shows it again. No window rule is required.

Expand **Caption overlay appearance** for background transparency, border thickness and retained history. These settings affect the captions only. Colors follow the current Omarchy theme. Background transparency does not fade the text. The default background is transparent and the 1 px border appears on focus; a value of −1 uses the theme's popup defaults.

Recognition uses overlapping audio chunks, five seconds by default. Longer chunks add sentence context and latency. Captions do not delay or synchronize video playback. If processing falls behind, the bounded queue drops old audio and reports it. Noise suppression and voice detection reduce unwanted captions but cannot isolate one speaker from all music or background voices.

## Privacy and resource use

Audio stays local. Recognized text goes to the selected translation endpoint; an online endpoint therefore receives that text and may charge your account. There is no telemetry or disk recording of captions/audio.

Saved tokens are optional owner-only plaintext in `credentials.json`, not an encrypted keychain. Use HTTPS for remote authenticated endpoints. Browser subscription login and automatic token refresh are not supported.

Stop closes the overlay immediately, then waits for in-flight inference and model/service cleanup. Provider requests may take up to 60 seconds; service shutdown can take up to 70 seconds. The plugin unloads newly used models and stops services/processes it started. It preserves pre-existing services and loaded models. Concurrent applications sharing a newly loaded model can be affected by unload; a dedicated endpoint avoids this conflict.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| Setup needed / no controller | Run the installed plugin's `setup.sh`; confirm `uv`, `ffmpeg`, `pactl` and `quickshell` are available. |
| No audio or no captions | Select the actual playback output, unmute playback and check the startup/status text. Refresh devices after changing hardware. |
| False captions or wrong source language | Use a multilingual speech model; set a source language override for short/noisy speech. English-only models require an English source override. |
| Translator unavailable | Check endpoint/model settings. Local backends need an existing installation; llama.cpp needs a compatible router/user service. |
| Online authentication error | Apply a valid provider-issued token, verify HTTPS and model access. Enter the model manually if discovery is unavailable. |
| Slow or late captions | Try a smaller recognition/translation model, reduce competing workload, and review queue-drop status. |
| Overlay disappears on another workspace | Return to the workspace where it opened. Capture remains active until Stop/Close. |
| Cleanup is slow | Allow an in-flight request to finish. Review status errors if the provider refuses unload. |

For reproducible reports, include your Omarchy version, provider type, model names, input type and error text. Do not share tokens, credential files or private speech content.

## Update

Stop translation, update the checkout and refresh its runtime:

```bash
omarchy plugin update ubruckhaus.video-trans
bash ~/.config/omarchy/plugins/ubruckhaus.video-trans/setup.sh
```

## Remove and clean up

Stop the session before removal:

```bash
omarchy plugin remove ubruckhaus.video-trans
```

Omarchy removes the plugin and its bar integration. Personal data and downloaded models remain. If you want to clean them up too, review and delete only the directories you no longer need:

| Default path | Contents |
| --- | --- |
| `~/.config/video-trans/` | Preferences and optional saved credentials |
| `~/.local/share/video-trans/` | Isolated Python runtime |
| `~/.cache/huggingface/hub/` | Shared model cache; other applications may use it |

Custom `XDG_CONFIG_HOME` and `XDG_DATA_HOME` change the first two locations. Do not delete the entire shared Hugging Face cache just to remove this plugin. Remove any optional Video Trans shortcut you added yourself.

## Optional keyboard shortcut

The [README](README.md#development-and-checks) includes a Hyprland Lua binding for Super + Ctrl + V. That example replaces Omarchy's Clipboard manager shortcut; add it only if you want that change. It toggles captions and capture together. Installation does not add a shortcut automatically.

Video Trans is an independent community plugin, licensed under [MIT](LICENSE).
