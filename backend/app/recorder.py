import threading
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import sounddevice as sd
import soundfile as sf

# Number of frequency bars streamed to the UI spectrum (matches the canvas).
SPECTRUM_BANDS = 56

# WAV subtype <-> human label, and the subtypes the UI may request.
_SUBTYPE_LABEL = {
    "PCM_16": "16-bit",
    "PCM_24": "24-bit",
    "PCM_32": "32-bit",
    "FLOAT": "32-bit float",
    "DOUBLE": "64-bit float",
}
_ALLOWED_SUBTYPES = {"PCM_16", "PCM_24", "PCM_32", "FLOAT"}


@dataclass
class RecorderStatus:
    state: str = "idle"  # idle | recording | paused
    file_path: Optional[str] = None
    started_at: Optional[str] = None
    paused: bool = False
    sample_rate: int = 48000
    mic_device: Optional[int] = None
    meeting_device: Optional[int] = None
    error: Optional[str] = None

    def to_dict(self):
        return asdict(self)


class RecCallRecorder:
    def __init__(self, recordings_dir: str, sample_rate: int = 48000, blocksize: int = 1024):
        self.recordings_dir = Path(recordings_dir)
        self.sample_rate = sample_rate
        self.blocksize = blocksize
        self.status = RecorderStatus(sample_rate=sample_rate)
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        # Elapsed-time tracking (pause-aware): seconds accumulated from finished
        # segments, plus the monotonic start of the segment currently running.
        self._accumulated = 0.0
        self._segment_start = 0.0
        self._current_subtype = "PCM_16"
        # Live frequency magnitudes (0..1) computed from the audio being
        # recorded, streamed to the UI so the spectrum reflects real sound.
        self._spectrum = [0.0] * SPECTRUM_BANDS

    def list_devices(self):
        devices = sd.query_devices()
        default_input, default_output = sd.default.device
        result = []
        for idx, dev in enumerate(devices):
            result.append({
                "id": idx,
                "name": dev["name"],
                "hostapi": sd.query_hostapis(dev["hostapi"])["name"],
                "max_input_channels": dev["max_input_channels"],
                "max_output_channels": dev["max_output_channels"],
                "default_samplerate": dev["default_samplerate"],
                "is_default_input": idx == default_input,
                "is_default_output": idx == default_output,
            })
        return result

    def list_recordings(self):
        self.recordings_dir.mkdir(parents=True, exist_ok=True)
        files = []
        for path in self.recordings_dir.rglob("*.wav"):
            stat = path.stat()
            entry = {
                "name": path.name,
                "path": str(path.relative_to(self.recordings_dir)),
                "size_bytes": stat.st_size,
                "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
                "modified_ts": stat.st_mtime,
                "duration_seconds": None,
                "sample_rate": None,
                "channels": None,
                "bit_depth": None,
            }
            try:
                info = sf.info(str(path))
                entry["duration_seconds"] = round(float(info.duration), 2)
                entry["sample_rate"] = int(info.samplerate)
                entry["channels"] = int(info.channels)
                entry["bit_depth"] = _SUBTYPE_LABEL.get(info.subtype, info.subtype)
            except Exception:
                pass
            files.append(entry)

        # Assign a stable sequential id in chronological order (oldest = 1),
        # then return newest first for display.
        files.sort(key=lambda x: x["modified_ts"])
        for i, f in enumerate(files, start=1):
            f["id"] = i
            del f["modified_ts"]
        files.sort(key=lambda x: x["id"], reverse=True)
        return files

    def _resolve_device(self, index, name):
        # Device indices shift when audio devices connect/disconnect (AirPods
        # especially), so a numeric id cached by the UI goes stale. When the UI
        # sends the device name, re-resolve it to the current index here.
        if name:
            for i, dev in enumerate(sd.query_devices()):
                if dev["max_input_channels"] > 0 and dev["name"] == name:
                    return i
            raise RuntimeError(
                f"Audio device “{name}” is no longer available. Click Refresh and try again."
            )
        return index

    def start(self, mic_device: Optional[int], meeting_device: int,
              mic_name: Optional[str] = None, meeting_name: Optional[str] = None,
              sample_rate: Optional[int] = None, subtype: Optional[str] = None):
        with self._lock:
            if self.status.state in {"recording", "paused"}:
                raise RuntimeError("Recording already active")

            mic_device = self._resolve_device(mic_device, mic_name)
            meeting_device = self._resolve_device(meeting_device, meeting_name)

            # Pick a sample rate both devices actually support, honouring the
            # requested quality when possible. Opening a 24 kHz device (e.g.
            # AirPods) at a hard-coded 48 kHz is what triggers PortAudio -9986,
            # so negotiate a common rate up front.
            rate = self._supported_rate(mic_device, meeting_device, sample_rate)
            if rate is None:
                raise RuntimeError(
                    "The selected microphone and meeting device share no common "
                    "sample rate. Try a different microphone."
                )
            self._current_subtype = subtype if subtype in _ALLOWED_SUBTYPES else "PCM_16"

            self._stop_event.clear()
            self._pause_event.clear()
            self._spectrum = [0.0] * SPECTRUM_BANDS
            now = datetime.now()
            day_dir = self.recordings_dir / now.strftime("%Y-%m-%d")
            day_dir.mkdir(parents=True, exist_ok=True)
            file_path = day_dir / f"RecCall_{now.strftime('%Y%m%d_%H%M%S')}.wav"

            self.status = RecorderStatus(
                state="recording",
                file_path=str(file_path),
                started_at=now.isoformat(timespec="seconds"),
                paused=False,
                sample_rate=rate,
                mic_device=mic_device,
                meeting_device=meeting_device,
                error=None,
            )
            self._accumulated = 0.0
            self._segment_start = time.monotonic()
            self._thread = threading.Thread(
                target=self._record_loop,
                args=(file_path, mic_device, meeting_device, rate, self._current_subtype),
                daemon=True,
            )
            self._thread.start()
            return self._status_dict()

    def pause(self):
        with self._lock:
            if self.status.state != "recording":
                raise RuntimeError("No active recording to pause")
            self._pause_event.set()
            self._accumulated += time.monotonic() - self._segment_start
            self.status.state = "paused"
            self.status.paused = True
            return self._status_dict()

    def resume(self):
        with self._lock:
            if self.status.state != "paused":
                raise RuntimeError("No paused recording to resume")
            self._pause_event.clear()
            self._segment_start = time.monotonic()
            self.status.state = "recording"
            self.status.paused = False
            return self._status_dict()

    def stop(self):
        with self._lock:
            if self.status.state == "idle":
                raise RuntimeError("No active recording to stop")
            self._stop_event.set()
            thread = self._thread

        if thread:
            thread.join(timeout=5)

        with self._lock:
            self.status.state = "idle"
            self.status.paused = False
            self._spectrum = [0.0] * SPECTRUM_BANDS
            return self._status_dict()

    def get_status(self):
        with self._lock:
            return self._status_dict()

    def get_spectrum(self):
        if self.status.state != "recording":
            return [0.0] * SPECTRUM_BANDS
        return list(self._spectrum)

    def delete_recording(self, recording_path: str):
        base = self.recordings_dir.resolve()
        target = (base / recording_path).resolve()
        if not str(target).startswith(str(base)) or not target.is_file():
            raise FileNotFoundError("Recording not found")

        with self._lock:
            active = self.status.file_path
            if (
                active
                and self.status.state in {"recording", "paused"}
                and Path(active).resolve() == target
            ):
                raise RuntimeError("Cannot delete a recording that is in progress")

        target.unlink()
        # Remove the day folder if it is now empty (keep the recordings root).
        parent = target.parent
        try:
            if parent != base and not any(parent.iterdir()):
                parent.rmdir()
        except OSError:
            pass

    def _compute_elapsed(self):
        if self.status.state == "recording":
            return round(self._accumulated + (time.monotonic() - self._segment_start), 3)
        if self.status.state == "paused":
            return round(self._accumulated, 3)
        return 0.0

    def _status_dict(self):
        data = self.status.to_dict()
        data["elapsed_seconds"] = self._compute_elapsed()
        data["bit_depth"] = _SUBTYPE_LABEL.get(self._current_subtype, "16-bit")
        return data

    def _supported_rate(self, mic_device, meeting_device, preferred=None):
        candidates = []
        if preferred:
            candidates.append(int(preferred))
        candidates += [48000, 44100, 32000, 24000, 16000]
        for dev in (mic_device, meeting_device):
            try:
                idx = sd.default.device[0] if dev is None else dev
                sr = int(round(sd.query_devices(idx)["default_samplerate"]))
                if sr not in candidates:
                    candidates.append(sr)
            except Exception:
                pass
        for sr in candidates:
            try:
                sd.check_input_settings(device=mic_device, channels=1, samplerate=sr)
                sd.check_input_settings(device=meeting_device, channels=1, samplerate=sr)
                return sr
            except Exception:
                continue
        return None

    def _update_spectrum(self, mono, rate):
        n = mono.shape[0]
        if n < 4:
            return
        windowed = mono * np.hanning(n)
        spec = np.abs(np.fft.rfft(windowed)) / n
        freqs = np.fft.rfftfreq(n, 1.0 / rate)
        edges = np.logspace(np.log10(60), np.log10(max(rate / 2, 1000)), SPECTRUM_BANDS + 1)
        bands = np.zeros(SPECTRUM_BANDS, dtype=np.float64)
        for i in range(SPECTRUM_BANDS):
            mask = (freqs >= edges[i]) & (freqs < edges[i + 1])
            mag = spec[mask].mean() if mask.any() else 0.0
            db = 20.0 * np.log10(mag + 1e-7)
            bands[i] = min(1.0, max(0.0, (db + 72.0) / 60.0))
        prev = np.asarray(self._spectrum)
        smoothed = 0.5 * prev + 0.5 * bands
        self._spectrum = [round(float(v), 3) for v in smoothed]

    def _record_loop(self, file_path: Path, mic_device: Optional[int], meeting_device: int,
                     rate: int, subtype: str = "PCM_16"):
        mic_latest = np.zeros((self.blocksize, 1), dtype=np.float32)
        meeting_latest = np.zeros((self.blocksize, 1), dtype=np.float32)
        mic_lock = threading.Lock()
        meeting_lock = threading.Lock()

        def mic_callback(indata, frames, callback_time, status):
            nonlocal mic_latest
            if status:
                pass
            with mic_lock:
                mic_latest = indata[:, :1].copy()

        def meeting_callback(indata, frames, callback_time, status):
            nonlocal meeting_latest
            if status:
                pass
            with meeting_lock:
                meeting_latest = indata[:, :1].copy()

        try:
            with sf.SoundFile(
                str(file_path),
                mode="w",
                samplerate=rate,
                channels=2,
                subtype=subtype,
            ) as wav_file:
                with sd.InputStream(
                    device=mic_device,
                    channels=1,
                    samplerate=rate,
                    blocksize=self.blocksize,
                    callback=mic_callback,
                ), sd.InputStream(
                    device=meeting_device,
                    channels=1,
                    samplerate=rate,
                    blocksize=self.blocksize,
                    callback=meeting_callback,
                ):
                    while not self._stop_event.is_set():
                        if self._pause_event.is_set():
                            time.sleep(0.05)
                            continue

                        with mic_lock:
                            left = mic_latest.copy()
                        with meeting_lock:
                            right = meeting_latest.copy()

                        frames = min(len(left), len(right))
                        stereo = np.column_stack([left[:frames, 0], right[:frames, 0]])
                        wav_file.write(stereo)
                        if frames:
                            self._update_spectrum(stereo.mean(axis=1), rate)
                        time.sleep(self.blocksize / rate)

        except Exception as exc:
            with self._lock:
                self.status.error = str(exc)
                self.status.state = "idle"
                self.status.paused = False
