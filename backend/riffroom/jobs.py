import asyncio
import json
import os
import shutil
import signal
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from uuid import uuid4

from riffroom.models import MODELS, PORTABLE_PROVIDER, resolve_model_variant
from riffroom.providers import PROVIDERS, SeparationProvider, is_provider_available
from riffroom.runtimes import AUDIO_SEPARATOR_ENV, AudioSeparatorRuntime
from riffroom.store import Store

ACTIVE = {"queued", "processing"}
_PROCESS_CONTROL_ERRORS = (ProcessLookupError, OSError, AttributeError, ValueError, NotImplementedError)
_DEFAULT = object()


def _process_group_kwargs(platform: str | None = None, creation_flag: int | None = None) -> dict:
    platform = os.name if platform is None else platform
    if platform != "nt":
        return {"start_new_session": True}
    flag = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if creation_flag is None else creation_flag
    return {"creationflags": flag} if flag else {}


async def _terminate_process(process, platform: str | None = None, ctrl_break_event=_DEFAULT):
    platform = os.name if platform is None else platform
    if platform == "nt":
        if ctrl_break_event is _DEFAULT:
            ctrl_break_event = getattr(signal, "CTRL_BREAK_EVENT", None)
        signalled = False
        if ctrl_break_event is not None:
            try:
                process.send_signal(ctrl_break_event)
                signalled = True
            except _PROCESS_CONTROL_ERRORS:
                pass
        if not signalled:
            try:
                process.terminate()
            except _PROCESS_CONTROL_ERRORS:
                pass
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except _PROCESS_CONTROL_ERRORS:
            pass

    try:
        await asyncio.wait_for(process.wait(), timeout=5)
    except asyncio.TimeoutError:
        try:
            if platform == "nt":
                process.kill()
            else:
                os.killpg(process.pid, signal.SIGKILL)
        except _PROCESS_CONTROL_ERRORS:
            pass
        try:
            await process.wait()
        except _PROCESS_CONTROL_ERRORS:
            pass
    except _PROCESS_CONTROL_ERRORS:
        pass


class Jobs:
    def __init__(
        self,
        store: Store,
        cache: Path,
        runtime: AudioSeparatorRuntime | None = None,
        provider_registry: Mapping[str, SeparationProvider] = PROVIDERS,
    ):
        self.store, self.cache = store, cache
        self.runtime = runtime
        self.provider_registry = provider_registry
        self.slots = asyncio.Semaphore(1)
        self.tasks: dict[str, asyncio.Task] = {}
        self.processes: dict[str, asyncio.subprocess.Process] = {}

    def _worker_environment(self) -> dict[str, str]:
        environment = {**os.environ, "PYTHONUNBUFFERED": "1"}
        if AUDIO_SEPARATOR_ENV not in environment and self.runtime is not None:
            executable = self.runtime.executable()
            if executable is not None:
                environment[AUDIO_SEPARATOR_ENV] = str(executable)
        return environment

    def _provider_available(self, provider_id: str) -> bool:
        if provider_id == PORTABLE_PROVIDER and self.runtime is not None:
            return self.runtime.executable() is not None
        return is_provider_available(provider_id, self.provider_registry)

    def start(self, track_id: str, model_id: str):
        if track_id in self.tasks:
            raise ValueError("This track is already being separated.")
        self.store.update(
            track_id, status="queued", message="Waiting for the separator", error=None, pending_model=model_id
        )
        self.tasks[track_id] = asyncio.create_task(self._run(track_id, model_id))

    async def _run(self, track_id: str, model_id: str):
        folder = self.store.directory(track_id)
        run_id = uuid4().hex
        output = folder / "runs" / run_id
        try:
            async with self.slots:
                variant = resolve_model_variant(MODELS[model_id], self._provider_available)
                if variant is None:
                    raise RuntimeError(
                        "No installed separation runtime is available for this model on this host."
                    )
                provider_id = variant.provider_id
                self.store.update(track_id, status="processing", message="Starting the separator")
                output.mkdir(parents=True)
                with (output / "job.log").open("w") as log:
                    spawn = asyncio.create_task(
                        asyncio.create_subprocess_exec(
                            sys.executable,
                            "-m",
                            "riffroom.worker",
                            str(folder / "original.wav"),
                            str(output),
                            str(self.cache),
                            model_id,
                            provider_id,
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.STDOUT,
                            env=self._worker_environment(),
                            limit=1024 * 1024,
                            **_process_group_kwargs(),
                        )
                    )
                    try:
                        process = await asyncio.shield(spawn)
                    except asyncio.CancelledError:
                        self.processes[track_id] = await spawn
                        raise
                    self.processes[track_id] = process
                    async for raw in process.stdout:
                        line = raw.decode(errors="replace")
                        log.write(line)
                        log.flush()
                        if line.startswith("RIFFROOM:"):
                            self.store.update(track_id, **json.loads(line.removeprefix("RIFFROOM:")))
                    code = await process.wait()
                if code != 0:
                    raise RuntimeError(
                        f"Separation stopped (exit {code}). Retry, or try Demucs if RoFormer ran out of memory. Details are in the job log."
                    )
                stems = json.loads((output / "stems.json").read_text())
                for stem in stems:
                    stem["url"] = f"/api/tracks/{track_id}/audio/{run_id}/{stem['file']}"
                track = self.store.get(track_id)
                runs = track.get("runs", []) + [
                    {
                        "id": run_id,
                        "model_id": model_id,
                        "provider_id": provider_id,
                        "stems": stems,
                    }
                ]
                self.store.update(
                    track_id,
                    status="ready",
                    message="Ready to practice",
                    runs=runs,
                    active_run=run_id,
                    pending_model=None,
                    error=None,
                )
        except asyncio.CancelledError:
            await self._kill_safely(track_id)
            self.store.update(
                track_id,
                status="ready" if self.store.get(track_id).get("runs") else "idle",
                message="Separation cancelled",
                pending_model=None,
            )
            shutil.rmtree(output, ignore_errors=True)
            raise
        except Exception as exc:
            await self._kill_safely(track_id)
            self.store.update(
                track_id,
                status="error",
                message="Separation didn't finish",
                error=str(exc),
                pending_model=None,
                failed_run=run_id,
            )
        finally:
            self.processes.pop(track_id, None)
            self.tasks.pop(track_id, None)

    async def _kill_safely(self, track_id):
        try:
            await self._kill(track_id)
        except Exception:
            pass

    async def _kill(self, track_id, *, platform=None, ctrl_break_event=_DEFAULT):
        process = self.processes.get(track_id)
        if process and getattr(process, "returncode", None) is None:
            await _terminate_process(process, platform, ctrl_break_event)

    async def cancel(self, track_id):
        task = self.tasks.get(track_id)
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            # A task cancelled before its first instruction has no finally block.
            self.tasks.pop(track_id, None)
            if self.store.get(track_id)["status"] in ACTIVE:
                self.store.update(
                    track_id,
                    status="ready" if self.store.get(track_id).get("runs") else "idle",
                    message="Separation cancelled",
                    pending_model=None,
                )

    async def close(self):
        for track_id in list(self.tasks):
            await self.cancel(track_id)
