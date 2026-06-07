"""Shared test fixtures.

The recorder talks to PortAudio via ``sounddevice``; tests replace that module
with an in-memory fake so the record loop runs without real audio hardware.
"""
import os
import shutil
import tempfile
import types

import numpy as np
import pytest

# main.py reads the recordings dir at import time — point it at a temp dir
# before anything imports the app.
_REC_DIR = tempfile.mkdtemp(prefix="reccall-test-")
os.environ["RECCALL_RECORDINGS_DIR"] = _REC_DIR

SUPPORTED_RATES = {48000, 44100, 32000, 24000, 16000}

# index 0 default-input mic (odd native rate to exercise the rate-append path),
# index 1 BlackHole (loopback input), index 2 output-only speaker.
FAKE_DEVICES = [
    {"name": "Mic A", "hostapi": 0, "max_input_channels": 1,
     "max_output_channels": 0, "default_samplerate": 22050.0},
    {"name": "BlackHole 2ch", "hostapi": 0, "max_input_channels": 2,
     "max_output_channels": 0, "default_samplerate": 48000.0},
    {"name": "Speaker", "hostapi": 0, "max_input_channels": 0,
     "max_output_channels": 2, "default_samplerate": 48000.0},
]


class FakeInputStream:
    """Context-manager stand-in for ``sd.InputStream`` that feeds one block."""

    raise_on_enter = False

    def __init__(self, **kwargs):
        self._callback = kwargs.get("callback")
        self._blocksize = kwargs.get("blocksize", 1024)

    def __enter__(self):
        if FakeInputStream.raise_on_enter:
            raise RuntimeError("Internal PortAudio error [PaErrorCode -9986]")
        if self._callback:
            n = self._blocksize
            block = (0.3 * np.sin(np.linspace(0, 6.283, n))).reshape(-1, 1).astype(np.float32)
            self._callback(block, n, None, "overflow")  # truthy status branch
            self._callback(block, n, None, None)
        return self

    def __exit__(self, *exc):
        return False


class FakeSD:
    def __init__(self):
        self.default = types.SimpleNamespace(device=(0, 2))
        self.InputStream = FakeInputStream
        self.unsupported_all = False

    def query_devices(self, index=None):
        if index is None:
            return [dict(d) for d in FAKE_DEVICES]
        return dict(FAKE_DEVICES[index])  # IndexError for out-of-range

    def query_hostapis(self, index):
        return {"name": "CoreAudio"}

    def check_input_settings(self, device=None, channels=1, samplerate=48000):
        if self.unsupported_all or samplerate not in SUPPORTED_RATES:
            raise RuntimeError("unsupported settings")


@pytest.fixture
def fake_sd(monkeypatch):
    import app.recorder as rec
    fsd = FakeSD()
    monkeypatch.setattr(rec, "sd", fsd)
    FakeInputStream.raise_on_enter = False
    yield fsd
    FakeInputStream.raise_on_enter = False


@pytest.fixture
def recorder(tmp_path, fake_sd):
    from app.recorder import RecCallRecorder
    rec = RecCallRecorder(str(tmp_path / "recs"))
    yield rec
    # Make sure no record thread is left looping.
    rec._stop_event.set()
    if rec._thread:
        rec._thread.join(timeout=2)


@pytest.fixture
def client(fake_sd):
    import app.main as main
    from app.recorder import RecCallRecorder
    from fastapi.testclient import TestClient

    base = main.RECORDINGS_DIR
    if os.path.isdir(base):
        shutil.rmtree(base)
    os.makedirs(base, exist_ok=True)
    # Fresh recorder state for each test.
    main.recorder = RecCallRecorder(base)
    with TestClient(main.app) as c:
        yield c
    main.recorder._stop_event.set()
    if main.recorder._thread:
        main.recorder._thread.join(timeout=2)
