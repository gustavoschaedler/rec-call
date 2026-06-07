# RecCall

RecCall is an MVP for recording calls on macOS:

- captures your **microphone** and the **meeting audio** (via BlackHole) into one stereo WAV;
- a recorder display with a **live spectrum**, big timer and status icon (it blinks while paused) — the selected mic, meeting device and quality are shown as **chips** right next to it;
- an **integrated player** — saved recordings play back in the same display with a real spectrum, and each row has a **play / pause** toggle;
- a **recordings list** with sequential id, duration, quality, modified date/time, download and delete (with confirmation), **paginated** (page size configurable in Settings);
- **light / dark themes** (with a matching logo per theme) and a Settings panel for device selection and **sound quality** (sample rate + bit depth).

## Important limitation on macOS + Docker

Docker Desktop on macOS runs inside a Linux VM and normally has no direct access to CoreAudio devices such as the microphone, AirPods, DJI Mic 2 or BlackHole.

For that reason, to capture audio on macOS run RecCall directly on the macOS host. The project also ships a Dockerfile/Compose setup to package the interface/API, but the actual audio capture on macOS must be done outside the container.

## Installation on macOS

### 1. Install BlackHole (required)

BlackHole is a virtual audio driver. RecCall uses it to capture the meeting audio (whatever your computer plays out), so **you must install it** — without it there is no meeting-audio device to record from.

```bash
brew install blackhole-2ch portaudio libsndfile
```

This installs BlackHole 2ch together with the PortAudio and libsndfile native libraries RecCall depends on.

> After installing BlackHole you may need to log out and back in (or reboot) for macOS to register the new audio device.

### 2. Install uv and run RecCall

The project uses [uv](https://docs.astral.sh/uv/) as its package/project manager. Install uv (if you do not have it yet):

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Then:

```bash
cd RecCall
uv sync          # creates the .venv and installs dependencies from uv.lock
uv run reccall   # starts the server
```

> `uv sync` reads `pyproject.toml`/`uv.lock` and uses the Python pinned in `.python-version` (3.12), downloading it automatically if needed.

Open:

```text
http://localhost:5055
```

## Audio configuration

Installing BlackHole on its own is not enough — it is just a "virtual audio cable". Without the steps below, the meeting audio still goes straight to your headphones and BlackHole receives nothing for RecCall to record. You need to route the meeting audio to **both** your headphones (so you can hear it) **and** BlackHole (so RecCall can capture it).

### 1. Create a Multi-Output Device (for the meeting audio)

1. Open **Audio MIDI Setup** (search for it with Spotlight).
2. Click the **`+`** in the bottom-left corner → **Create Multi-Output Device**.
3. Tick **both** boxes:
   - your real headphones/speakers (e.g. AirPods, the Mac's built-in speakers);
   - **`BlackHole 2ch`**.
4. (Recommended) Enable **Drift Correction** on the BlackHole row to avoid the two outputs drifting out of sync.

### 2. Point the meeting audio at that device

Pick where to set the output:

- **Globally** (simplest): in the macOS sound menu (or System Settings → Sound → Output), select the **Multi-Output Device**. Everything the computer plays then also reaches BlackHole.
- **Only the meeting app** (cleaner): inside **Zoom/Teams/Meet**, in the audio settings, choose the **Multi-Output Device** as the *Speaker/Output*. Only the call audio is then captured.

### 3. Select the devices in RecCall

Open the **⚙ Settings** dialog (top-right gear icon):

- **Microphone** → recorded to the **left channel**. Use `macOS Default Input` or pick a real mic. If your AirPods are also your output device, choose the built-in mic instead — macOS makes the AirPods microphone unavailable while they are playing audio.
- **Meeting audio / BlackHole** → recorded to the **right channel**; pick **`BlackHole 2ch`**.
- **Sound quality** → sample rate (`Auto` negotiates the best rate both devices support) and bit depth (16/24-bit PCM or 32-bit float).

The resulting WAV is stereo: left = you, right = the meeting.

> ⚠️ The Multi-Output Device is only for the **output** (the sound you hear). Your microphone is still captured separately by RecCall — do not try to merge mic + BlackHole into an "Aggregate Device", as RecCall already mixes the two into the stereo channels.

## Using the app

**Recorder.** The selected microphone, meeting device and quality appear as chips
next to the **Recorder** title, so you can confirm the setup at a glance. Hit
**Record** to start: the timer runs, the status icon turns red and the spectrum
reacts to the real audio (streamed from the server over a WebSocket). **Pause**
freezes the timer and blinks it; **Resume** continues; **Stop** finalises the WAV.

**Playback.** In **Saved recordings**, the play button is the first column after
the id. Pressing it plays the recording **inside the recorder display** (shared
spectrum and timer) and turns into a **pause** button. Use the row buttons (or the
inline audio controls) to pause/resume, and **Close** to return to recording mode.

**Recordings list.** Columns: `#` (sequential id), file, length, quality, size,
modified (date over time), and actions (download, delete). Delete asks for
confirmation. The list is **paginated** — change *Items per page* in Settings.

**Settings & theme.** The **⚙ gear** opens devices + sound quality + page size;
the **sun/moon** toggles light/dark (remembered across reloads). The app version
is shown next to the title.

## Docker

```bash
docker compose up --build
```

On macOS this mode is mainly for validating the interface/API. Audio capture generally will not work inside the container because of the Docker Desktop VM.

On Linux with ALSA/PulseAudio devices mapped through, capture can work by adapting `docker-compose.yml`.

## File format

Recordings are saved to:

```text
recordings/YYYY-MM-DD/RecCall_YYYYMMDD_HHMMSS.wav
```

Format:

- WAV, stereo;
- bit depth selectable in **Settings → Sound quality** (16-bit PCM by default; 24-bit PCM or 32-bit float);
- sample rate auto-negotiated to the highest both devices support (48 kHz when available), or forced from Settings;
- left channel: microphone;
- right channel: meeting audio / BlackHole.

## Development

Project layout:

```text
backend/app/
  main.py          FastAPI app: REST routes, /ws/spectrum, static mount
  recorder.py      recording engine (sounddevice + soundfile), spectrum FFT
  static/          web UI — vanilla HTML/CSS/JS, no build step
    index.html
    app.js
    styles.css
    logo-dark.png / logo-light.png
tests/             pytest suite (PortAudio mocked)
pyproject.toml     deps + project config (managed by uv)
```

The frontend is plain HTML/CSS/JS served by FastAPI — no bundler. In dev the
server sends `Cache-Control: no-cache` for static assets, and the asset URLs
carry a `?v=` query, so edits show up on a normal reload.

Runtime dependencies are pinned in `pyproject.toml` and locked in `uv.lock`. To upgrade everything to the latest releases:

```bash
uv lock --upgrade
uv sync
```

### Tests

The backend has a pytest suite that mocks PortAudio (no audio hardware needed) and enforces **100% line coverage**:

```bash
uv run pytest
```
