# Video Trans · User manual

**Live translated captions for videos, calls and other desktop audio on Omarchy.**

Video Trans recognizes speech locally with Whisper, translates it with your chosen provider, and displays captions in a movable window above fullscreen video. German is the initial target language. The bar popup controls the session; the caption window stays independent.

[Install](#install) · [First session](#your-first-session) · [Controls](#caption-controls) · [Troubleshooting](#troubleshooting) · [Remove](#remove-and-clean-up)

## Install

Use an Omarchy version with shell plugin support, running PipeWire-Pulse. Add the plugin:

```bash
omarchy plugin add https://github.com/uBruckhaus/omarchy-video-trans.git --enable
```

Then click the Video Trans bar icon and press **Set up now** in the **Not ready yet** card. It installs missing system packages after a password prompt, an isolated Python 3.12 environment with pinned PySide6, faster-whisper and httpx, and the `video-trans` command with desktop actions for shortcuts. It does not install a translator, assign keys or replace your settings. Internet access is needed for setup and uncached speech models. Terminal alternative: `omarchy pkg add ffmpeg libpulse uv`, then `bash ~/.config/omarchy/plugins/ubruckhaus.video-trans/setup.sh`.

Choose one translation backend before starting:

| Provider | What you need | Default endpoint |
| --- | --- | --- |
| llama.cpp | An existing user `llama-server.service`, router and text models | `http://127.0.0.1:8080` |
| Ollama | An existing Ollama installation and a downloaded text model | `http://127.0.0.1:11434` |
| Online | An OpenAI-compatible API, model and API key or bearer token | Your provider's HTTPS URL |

Whisper is the speech recognizer, not the translation provider. Video Trans does not download translation models. Local translation setup and shared-service behavior are documented in the [README](README.md#providers-and-authentication).

## Your first session

1. Click the Video Trans bar icon. While something is missing, the **Not ready yet** card names the next step, for example *step 1 of 3*, with one button that does it. **Other options** lists alternatives.
2. **Set up now** — once, as described under Install.
3. **Use <device>** — the playback device carrying your video; the default output comes first. Choose **Capture microphone instead** for speech in the room.
4. **Download Whisper …** — the speech model, once. Smaller models need fewer resources; larger ones are more accurate. Recognition runs on the CPU, keeping GPU memory for translation.
5. Translator — llama.cpp or Ollama start automatically when installed. If neither is, the card offers **Connect an online provider…**: enter the server address, model ID and API key on the provider page (paste with Ctrl+V), then **Apply token**. **Save token on this device** is optional.
6. **Choose a model automatically** — an installed text model suited to the target language. Review it in **Translation**; it is a name-based suggestion, not a benchmark.
7. When **✓ Ready** appears, start playback and press **▶ Start**. The bar icon turns green while captions run; right-click it to start or stop directly. If something fails at start, the startup check shows ✓ / ✕ per requirement with an explanation.

Change the target language in **Translation → Translate into** and the input in **Listening** before starting. Closing the popup leaves translation running when the caption window is visible. **■ Stop** and **Close caption window** stop capture and release owned resources.

## Caption controls

| Control | Effect |
| --- | --- |
| Drag with the left mouse button | Move the caption window |
| Drag the bottom-right handle | Resize the caption window (the handle shows while the pointer is over the captions) |
| Shift + drag | Select caption text |
| Mouse wheel | Read earlier captions |
| Follow new captions | Automatically scroll to newly received captions |
| Caption duration | Keep each caption visible for 1–120 seconds; default 5 |
| Caption font size | Change readability (12–64), including during translation; also `video-trans font bigger` / `smaller` or the Larger / Smaller caption text shortcuts |
| Caption text colour | Automatic (default: white or black for the video just above the captions), the theme, white, yellow, cyan, green, orange, pink, blue, black or `#rrggbb`; also `video-trans text-color next` / `toggle` |
| Show captions | Open the caption window without starting capture |
| Clear captions | Remove the retained text |
| ■ Stop / Close caption window | Close the caption window and end the session |

The caption overlay remains above fullscreen video on Wayland and belongs to the workspace where it opened. Switching workspaces hides it while capture continues; returning shows it again. No window rule is required.

In **Captions**, expand **Caption window appearance** for background transparency, border thickness and retained history. These settings affect the captions only. Colors follow the current Omarchy theme. Background transparency does not fade the text. The default background is transparent and the 1 px border appears on focus; a value of −1 uses the theme's popup defaults.

Recognition uses overlapping audio chunks, five seconds by default. Longer chunks add sentence context and latency. Captions do not delay or synchronize video playback. If processing falls behind, the bounded queue drops old audio and reports it. Noise suppression and voice detection reduce unwanted captions but cannot isolate one speaker from all music or background voices.

## Privacy and resource use

Audio stays local. Recognized text goes to the selected translation endpoint; an online endpoint therefore receives that text and may charge your account. There is no telemetry or disk recording of captions/audio.

**Automatic caption colour** (the default) samples the screen: every 2 seconds, while the caption window is open and Automatic is selected, `grim` captures a 60-pixel strip just above the caption window (below it when the window touches the top), downscaled to 5 %. The image is read from memory, only its mean brightness is kept, and nothing is stored, logged or sent anywhere. Choose any other caption colour to stop the sampling.

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
| `~/.local/bin/video-trans`, `~/.local/share/applications/video-trans.desktop` | Command and desktop actions for shortcuts |

Custom `XDG_CONFIG_HOME` and `XDG_DATA_HOME` change the first two locations. Do not delete the entire shared Hugging Face cache just to remove this plugin. Remove any optional Video Trans shortcut you added yourself.

## Shortcuts and actions

Setup adds a **Video Trans** application entry with desktop actions for every popup control: start / stop, start, stop, show, clear, follow new captions, caption text black / white, next caption text colour, larger / smaller caption text, audio output or microphone input, Whisper download, auto-select local model and refresh models. If Launch & Bind does not list them, press **Add shortcut actions** in the popup's **Captions** group. In Launch & Bind, open **Apps → Video Trans → Shortcuts**, choose an action and assign a key. Installation does not assign a key automatically.

The same actions run from a terminal as `video-trans <action>`; `video-trans help` lists them. Its tray menu offers them too, plus target language and audio input submenus; Launch & Bind lists it under **Plugins → Running in the bar**, like Screen Narrator. The tray is always there while the bar widget is, and its entries start Video Trans when needed.

The [README](README.md#development-and-checks) also shows a direct Hyprland Lua binding for Super + Ctrl + V. That example replaces Omarchy's Clipboard manager shortcut; add it only if you want that change.

Video Trans is an independent community plugin, licensed under [MIT](LICENSE).
