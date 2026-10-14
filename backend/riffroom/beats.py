"""Offline Beat This! analysis jobs and persisted beat-grid validation."""

import asyncio
import importlib.util
import math
import os
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Callable

from riffroom.store import Store

BEAT_MODEL = os.environ.get("RIFFROOM_BEAT_MODEL", "final0")
ANALYSIS_VERSION = 1


def beat_this_available() -> bool:
    return importlib.util.find_spec("beat_this") is not None


def beat_weights_prepared(checkpoint: str = BEAT_MODEL) -> bool:
    explicit = Path(checkpoint).expanduser()
    if explicit.is_file():
        return True
    if any(separator in checkpoint for separator in ("/", "\\")):
        return False
    torch_home = os.environ.get("TORCH_HOME")
    if torch_home:
        hub = Path(torch_home).expanduser() / "hub"
    else:
        cache = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")).expanduser()
        hub = cache / "torch" / "hub"
    return (hub / "checkpoints" / f"beat_this-{checkpoint}.ckpt").is_file()


def _package_version() -> str:
    try:
        return version("beat-this")
    except PackageNotFoundError:
        return "unknown"


def run_beat_this(path: Path, checkpoint: str) -> tuple[list[float], list[float]]:
    # Import lazily: the core app must remain usable without torch/Beat This!.
    from beat_this.inference import File2Beats

    tracker = File2Beats(checkpoint_path=checkpoint, device="cpu", dbn=False)
    beats, downbeats = tracker(str(path))
    return list(beats), list(downbeats)


def _clean_times(values, duration: float, label: str) -> list[float]:
    result = [float(value) for value in values]
    if not result or any(not math.isfinite(value) or value < 0 or value > duration for value in result):
        raise ValueError(f"Beat This! returned an invalid {label} grid.")
    if any(right <= left for left, right in zip(result, result[1:])):
        raise ValueError(f"Beat This! returned an unsorted {label} grid.")
    return result


class BeatJobs:
    def __init__(
        self,
        store: Store,
        runner: Callable[[Path, str], tuple[list[float], list[float]]] = run_beat_this,
        available: Callable[[], bool] = beat_this_available,
    ):
        self.store = store
        self.runner = runner
        self.available = available
        self.tasks: dict[str, asyncio.Task] = {}
        self.slot = asyncio.Semaphore(1)

    def status(self) -> dict:
        return {
            "available": self.available(),
            "weights_prepared": beat_weights_prepared(),
            "model": BEAT_MODEL,
            "provider": "CPJKU/beat_this",
        }

    def start(self, track_id: str, *, retry: bool = False) -> None:
        """Persist one attempt; only an explicit retry may replace a failed attempt."""
        with self.store.lock:
            track = self.store.get(track_id)
            analysis = track.get("beat_analysis") or {}
            status = analysis.get("status")
            if track_id in self.tasks or status in {"ready", "queued", "processing"}:
                return
            if status == "error" and not retry:
                return
            if not self.available():
                self.store.update(track_id, beat_analysis={
                    "status": "error",
                    "message": "Beat analysis unavailable",
                    "error": "Beat tracking is not installed. Install Riffroom's beat optional dependency, then Retry.",
                })
                return
            track["beat_analysis"] = {
                "status": "queued",
                "message": "Waiting to analyze the original mix",
                "error": None,
            }
            self.store.put(track)
            self.tasks[track_id] = asyncio.create_task(self._run(track_id))

    async def _run(self, track_id: str) -> None:
        try:
            async with self.slot:
                track = self.store.get(track_id)
                analysis = dict(track["beat_analysis"])
                analysis.update(status="processing", message="Finding beats and downbeats")
                self.store.update(track_id, beat_analysis=analysis)
                source = self.store.directory(track_id) / "original.wav"
                beats, downbeats = await asyncio.to_thread(self.runner, source, BEAT_MODEL)
                current = self.store.get(track_id)
                beats = _clean_times(beats, current["duration"], "beat")
                downbeats = _clean_times(downbeats, current["duration"], "downbeat")
                # A useful grid needs a local interval; a lone timestamp cannot drive a count-in.
                if len(beats) < 2:
                    raise ValueError("Beat This! did not find enough beats for a click grid.")
                if any(min(abs(downbeat - beat) for beat in beats) > 0.07 for downbeat in downbeats):
                    raise ValueError("Beat This! returned downbeats that do not align with its beat grid.")
                self.store.update(
                    track_id,
                    beat_analysis={
                        "status": "ready",
                        "message": f"Found {len(beats)} beats",
                        "error": None,
                        "beats": beats,
                        "downbeats": downbeats,
                        "time_signature": 4,
                        "time_signature_source": "default",
                        "analysis_version": ANALYSIS_VERSION,
                        "provider": "CPJKU/beat_this",
                        "model": BEAT_MODEL,
                        "package_version": _package_version(),
                        "source": "original_mix",
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    },
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            try:
                self.store.update(
                    track_id,
                    beat_analysis={
                        "status": "error",
                        "message": "Beat analysis did not finish",
                        "error": str(exc),
                    },
                )
            except KeyError:
                pass
        finally:
            self.tasks.pop(track_id, None)

    async def cancel(self, track_id: str) -> None:
        task = self.tasks.get(track_id)
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            self.tasks.pop(track_id, None)

    async def close(self) -> None:
        for track_id in list(self.tasks):
            await self.cancel(track_id)
