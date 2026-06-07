import asyncio
import os
from importlib.metadata import PackageNotFoundError, version as pkg_version
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .recorder import RecCallRecorder

try:
    APP_VERSION = pkg_version("reccall")
except PackageNotFoundError:  # pragma: no cover - package metadata is always present in practice
    APP_VERSION = "0.0.0"

RECORDINGS_DIR = os.getenv("RECCALL_RECORDINGS_DIR", str(Path.cwd() / "recordings"))
HOST = os.getenv("RECCALL_HOST", "127.0.0.1")
PORT = int(os.getenv("RECCALL_PORT", "5055"))

app = FastAPI(title="RecCall")
recorder = RecCallRecorder(RECORDINGS_DIR)


@app.middleware("http")
async def no_store_static(request: Request, call_next):
    # Static assets (index.html / app.js / styles.css) change often in dev;
    # tell the browser to always revalidate so edits show up on a plain reload.
    response = await call_next(request)
    if not request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-cache, max-age=0"
    return response


class StartRequest(BaseModel):
    mic_device: Optional[int] = None
    meeting_device: int
    # Names let the server re-resolve devices whose indices have shifted.
    mic_name: Optional[str] = None
    meeting_name: Optional[str] = None
    # Sound-quality preferences (auto-negotiated when unset / unsupported).
    sample_rate: Optional[int] = None
    subtype: Optional[str] = None


@app.get("/api/devices")
def devices():
    try:
        return {"devices": recorder.list_devices()}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/version")
def app_version():
    return {"version": APP_VERSION}


@app.get("/api/status")
def status():
    return recorder.get_status()


@app.websocket("/ws/spectrum")
async def ws_spectrum(ws: WebSocket):
    await ws.accept()
    try:
        while True:
            await ws.send_json(recorder.get_spectrum())
            await asyncio.sleep(0.04)  # ~25 fps
    except (WebSocketDisconnect, RuntimeError):
        # Client went away (RuntimeError covers "close message already sent").
        pass


@app.post("/api/recordings/start")
def start(req: StartRequest):
    try:
        return recorder.start(
            req.mic_device, req.meeting_device, req.mic_name, req.meeting_name,
            req.sample_rate, req.subtype,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/recordings/pause")
def pause():
    try:
        return recorder.pause()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/recordings/resume")
def resume():
    try:
        return recorder.resume()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/recordings/stop")
def stop():
    try:
        return recorder.stop()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/recordings")
def recordings():
    return {"recordings": recorder.list_recordings()}


@app.get("/api/recordings/download/{recording_path:path}")
def download(recording_path: str):
    base = Path(RECORDINGS_DIR).resolve()
    target = (base / recording_path).resolve()
    if not str(target).startswith(str(base)) or not target.exists():
        raise HTTPException(status_code=404, detail="Recording not found")
    return FileResponse(str(target), media_type="audio/wav", filename=target.name)


@app.delete("/api/recordings/{recording_path:path}")
def delete_recording(recording_path: str):
    try:
        recorder.delete_recording(recording_path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Recording not found")
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"deleted": recording_path}


app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")


def main():  # pragma: no cover - process entrypoint, exercised via the CLI
    import uvicorn
    uvicorn.run("app.main:app", host=HOST, port=PORT, reload=False)


if __name__ == "__main__":
    main()
