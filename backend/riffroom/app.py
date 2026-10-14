import asyncio
import ipaddress
import math
import os
import shutil
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from starlette.datastructures import Headers
from starlette.middleware.trustedhost import TrustedHostMiddleware

from riffroom.audio import decode, waveform
from riffroom.beat_grid_prototype import propose_correction
from riffroom.beats import BeatJobs
from riffroom.jobs import ACTIVE, InvalidSeparationSource, Jobs
from riffroom.models import MLX_PROVIDER, MODELS, PORTABLE_PROVIDER, catalog, clear_model_cache
from riffroom.providers import is_provider_available
from riffroom.runtimes import AudioSeparatorRuntime
from riffroom.store import Store

ROOT = Path(__file__).resolve().parents[2]
DATA = Path(os.environ.get("RIFFROOM_DATA", ROOT / "data")).resolve()
MAX_BYTES = 512 * 1024 * 1024


class BindTrustedHostMiddleware(TrustedHostMiddleware):
    """Handle bracketed IPv6 literals, which TrustedHostMiddleware splits at ':'."""

    async def __call__(self, scope, receive, send):
        if scope["type"] in {"http", "websocket"}:
            host = Headers(scope=scope).get("host", "")
            try:
                parsed = urlsplit("//" + host)
                address = parsed.hostname
                # Accessing port validates the optional numeric suffix.
                parsed.port
                trusted_ipv6 = (host.startswith("[") and address
                                and ipaddress.ip_address(address).version == 6
                                and address in self.allowed_hosts)
            except ValueError:
                trusted_ipv6 = False
            if trusted_ipv6:
                await self.app(scope, receive, send)
                return
        await super().__call__(scope, receive, send)


class PracticeLoop(BaseModel):
    model_config = ConfigDict(strict=True, allow_inf_nan=False)
    id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=60)
    a: float = Field(ge=0)
    b: float
    enabled: bool

    @field_validator("a", "b", mode="before")
    @classmethod
    def finite_boundary(cls, value):
        # Avoid echoing non-JSON NaN/Infinity in FastAPI's validation response.
        if isinstance(value, float) and not math.isfinite(value):
            raise HTTPException(422, "Loop boundaries must be finite numbers")
        return value

    @field_validator("id", "name", mode="before")
    @classmethod
    def trim_text(cls, value):
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def valid_length(self):
        if self.b - self.a < 0.05 - 1e-9:
            raise ValueError("Loops must be at least 0.05 seconds long")
        return self


class PracticeRequest(BaseModel):
    loops: list[PracticeLoop] = Field(max_length=50)

    @model_validator(mode="after")
    def unique_ids(self):
        if len({loop.id for loop in self.loops}) != len(self.loops):
            raise ValueError("Loop ids must be unique")
        return self


class SeparationSource(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["original", "stem"] = "original"
    run_id: str | None = None
    stem_name: str | None = None

    @model_validator(mode="after")
    def valid_reference(self):
        if self.type == "stem" and (not self.run_id or not self.stem_name):
            raise ValueError("Stem sources require a run_id and stem_name")
        if self.type == "original" and (self.run_id is not None or self.stem_name is not None):
            raise ValueError("Original sources cannot include stem lineage")
        return self


class SeparationRequest(BaseModel):
    model_id: str
    source: SeparationSource = Field(default_factory=SeparationSource)


class ExpansionRequest(BaseModel):
    run_id: str | None = None


def create_app(data: Path = DATA, frontend: Path = ROOT / "frontend" / "dist"):
    store = Store(data / "tracks")
    runtime = AudioSeparatorRuntime(data)
    jobs = Jobs(store, data / "models", runtime)
    beat_jobs = BeatJobs(store)

    @asynccontextmanager
    async def lifespan(app):
        for track in store.list():
            if track["status"] in ACTIVE:
                store.update(
                    track["id"],
                    status="error",
                    pending_model=None,
                    pending_source=None,
                    error="The app stopped during separation. You can retry.",
                    message="Interrupted",
                )
            analysis = track.get("beat_analysis")
            if isinstance(analysis, dict) and analysis.get("status") in ACTIVE:
                store.update(
                    track["id"],
                    beat_analysis={
                        "status": "error",
                        "message": "Beat analysis did not finish",
                        "error": "The app stopped during beat analysis. You can retry.",
                    },
                )
        yield
        await jobs.close()
        await beat_jobs.close()
        await runtime.close()

    app = FastAPI(title="Riffroom", lifespan=lifespan)
    app.state.store, app.state.jobs, app.state.beat_jobs = store, jobs, beat_jobs
    app.state.audio_separator_runtime = runtime
    allowed_hosts = ["127.0.0.1", "localhost", "testserver"]
    bind_host = os.environ.get("RIFFROOM_BIND_HOST")
    if bind_host in {"0.0.0.0", "::"}:
        allowed_hosts = ["*"]
    elif bind_host:
        allowed_hosts.append(bind_host)
    app.add_middleware(BindTrustedHostMiddleware, allowed_hosts=allowed_hosts)

    @app.middleware("http")
    async def same_origin(request: Request, call_next):
        # Reject cross-site mutations (including form uploads), also in opt-in LAN mode.
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
        return catalog(
            jobs.cache,
            provider_availability={
                MLX_PROVIDER: is_provider_available(MLX_PROVIDER),
                PORTABLE_PROVIDER: runtime.status()["available"] is True,
            },
        )

    @app.get("/api/runtimes/audio-separator")
    def audio_separator_runtime_status():
        return runtime.status()

    @app.get("/api/runtimes/beat-tracking")
    def beat_tracking_status():
        return beat_jobs.status()

    @app.post("/api/runtimes/audio-separator/install", status_code=202)
    async def install_audio_separator_runtime():
        return runtime.start_install()

    @app.delete("/api/models/{model_id}/cache", status_code=204)
    def delete_model_cache(model_id: str):
        model = MODELS.get(model_id)
        if model is None:
            raise HTTPException(404, "Separation model not found.")
        if not model.cache_cleanup_supported:
            detail = (
                "Prepared-file cleanup is unavailable for this portable model."
                if any(variant.provider_id == PORTABLE_PROVIDER for variant in model.variants)
                else "Prepared-file cleanup is unavailable for this shared model config."
            )
            raise HTTPException(409, detail)
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

    @app.put("/api/tracks/{track_id}/practice")
    def save_practice(track_id: str, request: PracticeRequest):
        current = store.get(track_id)
        if any(loop.b > current["duration"] for loop in request.loops):
            raise HTTPException(422, "Loop end exceeds track duration")
        return store.update(track_id, practice=request.model_dump())

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
                    "next_take_number": 1,
                    "active_run": None,
                    "peaks": peaks,
                    "error": None,
                }
            )
            source.unlink()
            jobs.start(track_id, model_id)
            beat_jobs.start(track_id)
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
            source = body.source.model_dump()
            if source["type"] == "original":
                jobs.start(track_id, body.model_id)
            else:
                jobs.start(track_id, body.model_id, source)
        except InvalidSeparationSource as exc:
            raise HTTPException(400, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return store.get(track_id)

    @app.get("/api/tracks/{track_id}/beats/correction")
    def beat_correction(track_id: str):
        """Ephemeral proposal from stored analysis; no inference or manifest writes."""
        analysis = store.get(track_id).get("beat_analysis")
        if not analysis or analysis.get("status") != "ready":
            raise HTTPException(409, "Stored ready beat analysis is required for correction.")
        if analysis.get("provider") != "CPJKU/beat_this":
            raise HTTPException(409, "Experimental correction requires stored Beat This! analysis.")
        try:
            report = propose_correction(
                analysis["beats"], analysis["downbeats"], analysis["time_signature"],
                source_provenance=analysis,
            )
        except Exception as exc:
            # Fail explicitly; never publish a raw grid disguised as a repair.
            raise HTTPException(422, "Experimental beat correction failed for this stored analysis.") from exc
        proposal = report["proposal"]
        return {
            "status": "applied" if proposal["accepted_repairs"] else "no_confident_repair",
            "source_analysis": analysis,
            "grid": {"beats": proposal["beats"], "downbeats": proposal["downbeats"],
                     "time_signature": analysis["time_signature"]},
            "report": report,
        }

    @app.post("/api/tracks/{track_id}/beats/prepare", status_code=202)
    async def prepare_beats(track_id: str):
        # Opening a legacy track is idempotent, including across reloads and failures.
        beat_jobs.start(track_id)
        return store.get(track_id)

    @app.post("/api/tracks/{track_id}/beats", status_code=202)
    async def analyze_beats(track_id: str):
        beat_jobs.start(track_id, retry=True)
        return store.get(track_id)

    @app.put("/api/tracks/{track_id}/runs/{parent_id}/expansions/{stem_name}")
    def select_expansion(track_id: str, parent_id: str, stem_name: str, body: ExpansionRequest):
        with store.lock:
            track = store.get(track_id)
            if track["status"] in ACTIVE:
                raise HTTPException(409, "Wait for separation to finish before changing a split.")
            parent = next((run for run in track.get("runs", []) if run["id"] == parent_id), None)
            if parent is None:
                raise HTTPException(404, "Parent separation result not found.")
            if stem_name not in {stem.get("name") for stem in parent.get("stems", [])}:
                raise HTTPException(404, "Parent stem not found.")
            if body.run_id is not None:
                child = next((run for run in track["runs"] if run["id"] == body.run_id), None)
                expected = {"type": "stem", "run_id": parent_id, "stem_name": stem_name}
                if child is None or child.get("source") != expected:
                    raise HTTPException(400, "That child result does not belong to this stem.")
            active_children = dict(parent.get("active_children", {}))
            if body.run_id is None:
                active_children.pop(stem_name, None)
            else:
                active_children[stem_name] = body.run_id
            parent["active_children"] = active_children
            return store.put(track)

    @app.post("/api/tracks/{track_id}/cancel")
    async def cancel(track_id: str):
        store.get(track_id)
        await jobs.cancel(track_id)
        return store.get(track_id)

    @app.delete("/api/tracks/{track_id}", status_code=204)
    async def delete(track_id: str):
        store.get(track_id)
        await jobs.cancel(track_id)
        await beat_jobs.cancel(track_id)
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

            removed_ids = {run_id}
            while True:
                descendants = {
                    item["id"]
                    for item in track["runs"]
                    if isinstance(item.get("source"), dict)
                    and item["source"].get("run_id") in removed_ids
                }
                if descendants <= removed_ids:
                    break
                removed_ids.update(descendants)
            remaining = [item for item in track["runs"] if item["id"] not in removed_ids]
            for item in remaining:
                item["active_children"] = {
                    stem: child_id
                    for stem, child_id in item.get("active_children", {}).items()
                    if child_id not in removed_ids
                }
            if track.get("active_run") in removed_ids:
                roots = [item for item in remaining if Store.is_root_run(item)]
                track["active_run"] = roots[-1]["id"] if roots else None
            track["runs"] = remaining

            # Make the manifest authoritative before touching audio files. On
            # Windows a browser response can briefly keep a stem open even
            # after the mixer switches, so physical cleanup must not turn a
            # completed logical deletion into a 500 response.
            store.put(track)
            for removed_id in removed_ids:
                # IDs come from the matched manifest, never an untrusted path parameter.
                if (
                    not isinstance(removed_id, str)
                    or Path(removed_id).name != removed_id
                    or removed_id in {".", ".."}
                ):
                    continue
                run_folder = store.directory(track_id) / "runs" / removed_id
                try:
                    shutil.rmtree(run_folder)
                except OSError:
                    pass

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
