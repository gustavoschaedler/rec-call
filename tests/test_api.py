import time
from pathlib import Path

import numpy as np
import soundfile as sf

from app.recorder import SPECTRUM_BANDS


def _make_wav(base, rel, seconds=0.1, rate=48000):
    path = Path(base) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), np.zeros((int(rate * seconds), 2), dtype=np.float32), rate, subtype="PCM_16")
    return path


# ---------------- simple GETs ----------------

def test_devices(client):
    body = client.get("/api/devices").json()
    assert [d["name"] for d in body["devices"]] == ["Mic A", "BlackHole 2ch", "Speaker"]


def test_devices_error_returns_500(client, monkeypatch):
    import app.main as main

    def boom():
        raise RuntimeError("device failure")

    monkeypatch.setattr(main.recorder, "list_devices", boom)
    res = client.get("/api/devices")
    assert res.status_code == 500
    assert res.json()["detail"] == "device failure"


def test_version(client):
    body = client.get("/api/version").json()
    assert "version" in body and body["version"]


def test_status_idle(client):
    body = client.get("/api/status").json()
    assert body["state"] == "idle"
    assert body["elapsed_seconds"] == 0.0


def test_recordings_listing(client):
    import app.main as main
    _make_wav(main.RECORDINGS_DIR, "2099-05-05/sample.wav")
    body = client.get("/api/recordings").json()
    assert len(body["recordings"]) == 1
    assert body["recordings"][0]["id"] == 1


# ---------------- websocket ----------------

def test_ws_spectrum(client):
    with client.websocket_connect("/ws/spectrum") as ws:
        data = ws.receive_json()
    assert isinstance(data, list)
    assert len(data) == SPECTRUM_BANDS


def test_ws_spectrum_handles_disconnect(client):
    """Drive the handler directly so the disconnect-cleanup branch is exercised."""
    import asyncio

    from fastapi import WebSocketDisconnect

    import app.main as main

    class FakeWS:
        def __init__(self):
            self.sent = 0

        async def accept(self):
            pass

        async def send_json(self, payload):
            self.sent += 1
            if self.sent >= 2:
                raise WebSocketDisconnect(code=1000)

    ws = FakeWS()
    asyncio.run(main.ws_spectrum(ws))
    assert ws.sent == 2


# ---------------- record lifecycle ----------------

def test_record_lifecycle(client):
    started = client.post("/api/recordings/start", json={"mic_device": 0, "meeting_device": 1}).json()
    assert started["state"] == "recording"
    time.sleep(0.1)

    assert client.post("/api/recordings/pause").json()["state"] == "paused"
    assert client.post("/api/recordings/resume").json()["state"] == "recording"
    time.sleep(0.05)
    assert client.post("/api/recordings/stop").json()["state"] == "idle"

    recs = client.get("/api/recordings").json()["recordings"]
    assert len(recs) == 1


def test_start_error_returns_400(client):
    res = client.post("/api/recordings/start",
                      json={"meeting_device": 1, "meeting_name": "Ghost Device"})
    assert res.status_code == 400
    assert "no longer available" in res.json()["detail"]


def test_pause_error_returns_400(client):
    res = client.post("/api/recordings/pause")
    assert res.status_code == 400


def test_resume_error_returns_400(client):
    res = client.post("/api/recordings/resume")
    assert res.status_code == 400


def test_stop_error_returns_400(client):
    res = client.post("/api/recordings/stop")
    assert res.status_code == 400


# ---------------- download / delete ----------------

def test_download_success(client):
    import app.main as main
    _make_wav(main.RECORDINGS_DIR, "2099-06-06/take.wav")
    res = client.get("/api/recordings/download/2099-06-06/take.wav")
    assert res.status_code == 200
    assert res.headers["content-type"] == "audio/wav"


def test_download_not_found(client):
    res = client.get("/api/recordings/download/nope.wav")
    assert res.status_code == 404


def test_delete_success(client):
    import app.main as main
    _make_wav(main.RECORDINGS_DIR, "2099-07-07/gone.wav")
    res = client.request("DELETE", "/api/recordings/2099-07-07/gone.wav")
    assert res.status_code == 200
    assert res.json()["deleted"] == "2099-07-07/gone.wav"


def test_delete_not_found(client):
    res = client.request("DELETE", "/api/recordings/missing.wav")
    assert res.status_code == 404


def test_delete_in_progress_returns_409(client):
    client.post("/api/recordings/start", json={"mic_device": 0, "meeting_device": 1})
    time.sleep(0.1)
    import app.main as main
    rel = str(Path(main.recorder.status.file_path).relative_to(main.RECORDINGS_DIR))
    res = client.request("DELETE", f"/api/recordings/{rel}")
    assert res.status_code == 409
    client.post("/api/recordings/stop")


# ---------------- middleware + static ----------------

def test_static_index_has_no_cache_header(client):
    res = client.get("/")
    assert res.status_code == 200
    assert res.headers.get("cache-control") == "no-cache, max-age=0"
    assert "RecCall" in res.text


def test_api_responses_skip_cache_header(client):
    res = client.get("/api/version")
    assert res.headers.get("cache-control") is None
