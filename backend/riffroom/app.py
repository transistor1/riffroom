import asyncio
import os
import shutil
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.trustedhost import TrustedHostMiddleware

from riffroom.audio import decode, waveform
from riffroom.jobs import ACTIVE, Jobs
from riffroom.models import MODELS, catalog, clear_model_cache
from riffroom.store import Store

ROOT = Path(__file__).resolve().parents[2]
DATA = Path(os.environ.get("RIFFROOM_DATA", ROOT / "data")).resolve()
MAX_BYTES = 512 * 1024 * 1024


class SeparationRequest(BaseModel):
    model_id: str


def create_app(data: Path = DATA, frontend: Path = ROOT / "frontend" / "dist"):
    store = Store(data / "tracks")
    jobs = Jobs(store, data / "models")

    @asynccontextmanager
    async def lifespan(app):
        for track in store.list():
            if track["status"] in ACTIVE:
                store.update(
                    track["id"],
                    status="error",
                    pending_model=None,
                    error="The app stopped during separation. You can retry.",
                    message="Interrupted",
                )
        yield
        await jobs.close()

    app = FastAPI(title="Riffroom", lifespan=lifespan)
    app.state.store, app.state.jobs = store, jobs
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])

    @app.middleware("http")
    async def same_origin(request: Request, call_next):
        # Local-only app: reject cross-site mutations (including form uploads).
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            if origin and origin != f"{request.url.scheme}://{request.headers.get('host')}":
                return JSONResponse({"detail": "Cross-origin requests are not allowed."}, status_code=403)
            if request.headers.get("sec-fetch-site") == "cross-site":
                return JSONResponse({"detail": "Cross-site requests are not allowed."}, status_code=403)
        return await call_next(request)

    @app.exception_handler(KeyError)
    async def not_found(request, exc):
        return JSONResponse({"detail": "Track not found."}, status_code=404)

    @app.get("/api/health")
    def health():
        return {"name": "Riffroom", "ffmpeg": bool(shutil.which("ffmpeg")), "local": True}

    @app.get("/api/models")
    def models():
        return catalog(jobs.cache)

    @app.delete("/api/models/{model_id}/cache", status_code=204)
    def delete_model_cache(model_id: str):
        model = MODELS.get(model_id)
        if model is None:
            raise HTTPException(404, "Separation model not found.")
        with store.lock:
            in_use = any(
                track.get("status") in ACTIVE and track.get("pending_model") == model_id
                for track in store.list()
            )
            if in_use:
                raise HTTPException(
                    409,
                    "Wait for this model's active separation to finish before removing prepared files.",
                )
            clear_model_cache(model, jobs.cache)

    @app.get("/api/tracks")
    def tracks():
        return store.list()

    @app.get("/api/tracks/{track_id}")
    def track(track_id: str):
        return store.get(track_id)

    @app.post("/api/tracks", status_code=201)
    async def upload(file: UploadFile = File(...), model_id: str = Form("demucs-6")):
        if model_id not in MODELS:
            raise HTTPException(400, "Unknown separation model.")
        track_id = uuid4().hex
        folder = store.directory(track_id)
        folder.mkdir(parents=True)
        source = folder / "upload"
        try:
            size = 0
            with source.open("wb") as stream:
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise HTTPException(413, "Please choose a file smaller than 512 MB.")
                    stream.write(chunk)
            duration = await asyncio.to_thread(decode, source, folder / "original.wav")
            peaks = await asyncio.to_thread(waveform, folder / "original.wav")
            filename = Path(file.filename or "Untitled track").name
            store.put(
                {
                    "id": track_id,
                    "title": Path(filename).stem,
                    "filename": filename,
                    "duration": duration,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "status": "idle",
                    "message": "Imported",
                    "runs": [],
                    "active_run": None,
                    "peaks": peaks,
                    "error": None,
                }
            )
            source.unlink()
            jobs.start(track_id, model_id)
            return store.get(track_id)
        except BaseException as exc:
            shutil.rmtree(folder, ignore_errors=True)
            if isinstance(exc, ValueError):
                raise HTTPException(400, str(exc)) from exc
            raise
        finally:
            await file.close()

    @app.post("/api/tracks/{track_id}/separate", status_code=202)
    async def separate(track_id: str, body: SeparationRequest):
        store.get(track_id)
        if body.model_id not in MODELS:
            raise HTTPException(400, "Unknown separation model.")
        try:
            jobs.start(track_id, body.model_id)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return store.get(track_id)

    @app.post("/api/tracks/{track_id}/cancel")
    async def cancel(track_id: str):
        store.get(track_id)
        await jobs.cancel(track_id)
        return store.get(track_id)

    @app.delete("/api/tracks/{track_id}", status_code=204)
    async def delete(track_id: str):
        store.get(track_id)
        await jobs.cancel(track_id)
        shutil.rmtree(store.directory(track_id))

    @app.delete("/api/tracks/{track_id}/runs/{run_id}", status_code=204)
    def delete_run(track_id: str, run_id: str):
        with store.lock:
            track = store.get(track_id)
            if track["status"] in ACTIVE:
                raise HTTPException(409, "Wait for separation to finish before deleting a result.")
            run = next((item for item in track["runs"] if item["id"] == run_id), None)
            if run is None:
                raise HTTPException(404, "Separation result not found.")

            remaining = [item for item in track["runs"] if item["id"] != run_id]
            if track.get("active_run") == run_id:
                track["active_run"] = remaining[-1]["id"] if remaining else None
            track["runs"] = remaining

            # Use the manifest's matched ID, never the untrusted path parameter.
            run_folder = store.directory(track_id) / "runs" / run["id"]
            try:
                shutil.rmtree(run_folder)
            except FileNotFoundError:
                pass
            store.put(track)

    @app.get("/api/tracks/{track_id}/original")
    def original(track_id: str):
        store.get(track_id)
        return FileResponse(store.directory(track_id) / "original.wav", media_type="audio/wav")

    @app.get("/api/tracks/{track_id}/audio/{run_id}/{filename}")
    def audio(track_id: str, run_id: str, filename: str):
        track = store.get(track_id)
        run = next((r for r in track["runs"] if r["id"] == run_id), None)
        if not run or filename not in {s["file"] for s in run["stems"]}:
            raise HTTPException(404, "Stem not found.")
        return FileResponse(store.directory(track_id) / "runs" / run_id / filename, media_type="audio/wav")

    @app.get("/api/tracks/{track_id}/log")
    def log(track_id: str):
        track = store.get(track_id)
        run_id = track.get("failed_run")
        if not run_id:
            raise HTTPException(404, "No failed job log.")
        path = store.directory(track_id) / "runs" / run_id / "job.log"
        if not path.is_file():
            raise HTTPException(404, "No diagnostic log is available for this job.")
        return FileResponse(path, media_type="text/plain")

    if frontend.exists():
        app.mount("/", StaticFiles(directory=frontend, html=True), name="frontend")
    return app


app = create_app()
