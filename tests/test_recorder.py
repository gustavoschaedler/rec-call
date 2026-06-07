import time
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from app.recorder import RecCallRecorder, RecorderStatus, SPECTRUM_BANDS
from conftest import FakeInputStream


# ---------------- devices ----------------

def test_list_devices(recorder):
    devices = recorder.list_devices()
    assert len(devices) == 3
    mic = devices[0]
    assert mic["name"] == "Mic A"
    assert mic["hostapi"] == "CoreAudio"
    assert mic["is_default_input"] is True
    assert devices[2]["is_default_output"] is True


def test_resolve_device_by_name(recorder):
    assert recorder._resolve_device(99, "BlackHole 2ch") == 1


def test_resolve_device_missing_name_raises(recorder):
    with pytest.raises(RuntimeError, match="no longer available"):
        recorder._resolve_device(0, "Ghost Mic")


def test_resolve_device_without_name_keeps_index(recorder):
    assert recorder._resolve_device(7, None) == 7


# ---------------- sample-rate negotiation ----------------

def test_supported_rate_default(recorder):
    assert recorder._supported_rate(0, 1) == 48000


def test_supported_rate_prefers_requested(recorder):
    assert recorder._supported_rate(0, 1, preferred=24000) == 24000


def test_supported_rate_none_when_unsupported(recorder, fake_sd):
    fake_sd.unsupported_all = True
    assert recorder._supported_rate(0, 1) is None


def test_supported_rate_handles_bad_device_index(recorder):
    # query_devices(99) raises IndexError inside the default-rate probe; the
    # negotiation still resolves a usable rate.
    assert recorder._supported_rate(99, 1) == 48000


# ---------------- elapsed / status / spectrum ----------------

def test_compute_elapsed_states(recorder):
    assert recorder._compute_elapsed() == 0.0
    recorder.status.state = "recording"
    recorder._segment_start = time.monotonic()
    assert recorder._compute_elapsed() >= 0.0
    recorder.status.state = "paused"
    recorder._accumulated = 1.5
    assert recorder._compute_elapsed() == 1.5


def test_get_spectrum_idle_is_zeros(recorder):
    assert recorder.get_spectrum() == [0.0] * SPECTRUM_BANDS


def test_status_dict_has_extra_fields(recorder):
    data = recorder.get_status()
    assert data["elapsed_seconds"] == 0.0
    assert data["bit_depth"] == "16-bit"


def test_update_spectrum_short_input_noops(recorder):
    before = list(recorder._spectrum)
    recorder._update_spectrum(np.zeros(2), 48000)
    assert recorder._spectrum == before


def test_update_spectrum_with_tone(recorder):
    tone = 0.5 * np.sin(2 * np.pi * 440 * np.arange(1024) / 48000)
    for _ in range(4):
        recorder._update_spectrum(tone.astype(np.float32), 48000)
    assert max(recorder._spectrum) > 0.1


# ---------------- start / pause / resume / stop ----------------

def test_full_record_cycle(recorder):
    started = recorder.start(0, 1)
    assert started["state"] == "recording"
    assert started["sample_rate"] == 48000
    time.sleep(0.15)

    paused = recorder.pause()
    assert paused["state"] == "paused"
    time.sleep(0.12)  # let the loop sit in its paused branch

    resumed = recorder.resume()
    assert resumed["state"] == "recording"
    time.sleep(0.08)

    # spectrum is live while recording
    assert len(recorder.get_spectrum()) == SPECTRUM_BANDS

    stopped = recorder.stop()
    assert stopped["state"] == "idle"

    recs = recorder.list_recordings()
    assert len(recs) == 1
    assert recs[0]["sample_rate"] == 48000
    assert recs[0]["channels"] == 2
    assert recs[0]["duration_seconds"] > 0


def test_start_resolves_name_and_quality(recorder):
    started = recorder.start(0, 99, meeting_name="BlackHole 2ch",
                             sample_rate=24000, subtype="PCM_24")
    assert started["meeting_device"] == 1
    assert started["sample_rate"] == 24000
    assert started["bit_depth"] == "24-bit"
    time.sleep(0.08)
    recorder.stop()


def test_start_invalid_subtype_falls_back(recorder):
    recorder.start(0, 1, subtype="BOGUS")
    assert recorder._current_subtype == "PCM_16"
    time.sleep(0.05)
    recorder.stop()


def test_start_already_active(recorder):
    recorder.start(0, 1)
    time.sleep(0.05)
    with pytest.raises(RuntimeError, match="already active"):
        recorder.start(0, 1)
    recorder.stop()


def test_start_no_common_rate(recorder, fake_sd):
    fake_sd.unsupported_all = True
    with pytest.raises(RuntimeError, match="no common"):
        recorder.start(0, 1)


def test_pause_without_recording(recorder):
    with pytest.raises(RuntimeError, match="No active recording to pause"):
        recorder.pause()


def test_resume_without_pause(recorder):
    with pytest.raises(RuntimeError, match="No paused recording"):
        recorder.resume()


def test_stop_when_idle(recorder):
    with pytest.raises(RuntimeError, match="No active recording to stop"):
        recorder.stop()


def test_record_loop_reports_stream_error(recorder):
    FakeInputStream.raise_on_enter = True
    recorder.start(0, 1)
    time.sleep(0.15)
    assert recorder.status.state == "idle"
    assert "PaErrorCode" in (recorder.status.error or "")


# ---------------- list_recordings / delete ----------------

def _write_wav(path: Path, seconds=0.1, rate=48000):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = np.zeros((int(rate * seconds), 2), dtype=np.float32)
    sf.write(str(path), data, rate, subtype="PCM_16")


def test_list_recordings_skips_unreadable(recorder):
    base = recorder.recordings_dir
    _write_wav(base / "2099-01-01" / "good.wav")
    bad = base / "2099-01-01" / "bad.wav"
    bad.write_bytes(b"not a wav")
    recs = recorder.list_recordings()
    assert len(recs) == 2
    ids = sorted(r["id"] for r in recs)
    assert ids == [1, 2]
    bad_entry = next(r for r in recs if r["name"] == "bad.wav")
    assert bad_entry["duration_seconds"] is None


def test_delete_recording_not_found(recorder):
    recorder.recordings_dir.mkdir(parents=True, exist_ok=True)
    with pytest.raises(FileNotFoundError):
        recorder.delete_recording("missing.wav")


def test_delete_recording_traversal_blocked(recorder):
    recorder.recordings_dir.mkdir(parents=True, exist_ok=True)
    with pytest.raises(FileNotFoundError):
        recorder.delete_recording("../../etc/hosts")


def test_delete_recording_removes_empty_day_folder(recorder):
    base = recorder.recordings_dir
    day = base / "2099-02-02"
    _write_wav(day / "only.wav")
    recorder.delete_recording("2099-02-02/only.wav")
    assert not day.exists()


def test_delete_recording_keeps_nonempty_folder(recorder):
    base = recorder.recordings_dir
    day = base / "2099-03-03"
    _write_wav(day / "a.wav")
    _write_wav(day / "b.wav")
    recorder.delete_recording("2099-03-03/a.wav")
    assert day.exists()
    assert (day / "b.wav").exists()


def test_delete_recording_in_root(recorder):
    base = recorder.recordings_dir
    _write_wav(base / "loose.wav")
    recorder.delete_recording("loose.wav")
    assert base.exists()
    assert not (base / "loose.wav").exists()


def test_delete_recording_in_progress(recorder):
    recorder.start(0, 1)
    time.sleep(0.1)
    rel = str(Path(recorder.status.file_path).relative_to(recorder.recordings_dir))
    with pytest.raises(RuntimeError, match="in progress"):
        recorder.delete_recording(rel)
    recorder.stop()


def test_delete_recording_cleanup_oserror(recorder, monkeypatch):
    base = recorder.recordings_dir
    day = base / "2099-04-04"
    _write_wav(day / "x.wav")

    def boom(self):
        raise OSError("nope")

    monkeypatch.setattr(Path, "rmdir", boom)
    # Should swallow the OSError from the empty-folder cleanup.
    recorder.delete_recording("2099-04-04/x.wav")
    assert not (day / "x.wav").exists()


def test_recorder_status_to_dict():
    status = RecorderStatus(state="recording", sample_rate=44100)
    data = status.to_dict()
    assert data["state"] == "recording"
    assert data["sample_rate"] == 44100
