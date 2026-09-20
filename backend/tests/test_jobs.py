import asyncio
import sys
from uuid import uuid4

from riffroom.jobs import Jobs
from riffroom.store import Store


def test_worker_environment_injects_resolved_runtime_without_overriding_admin(tmp_path, monkeypatch):
    executable = tmp_path / "audio-separator"
    executable.touch(mode=0o755)

    class Runtime:
        def executable(self):
            return executable

    jobs = Jobs(Store(tmp_path / "tracks"), tmp_path / "models", Runtime())
    monkeypatch.delenv("RIFFROOM_AUDIO_SEPARATOR_BIN", raising=False)
    assert jobs._worker_environment()["RIFFROOM_AUDIO_SEPARATOR_BIN"] == str(executable)

    monkeypatch.setenv("RIFFROOM_AUDIO_SEPARATOR_BIN", "/administrator/override")
    assert jobs._worker_environment()["RIFFROOM_AUDIO_SEPARATOR_BIN"] == "/administrator/override"


def test_cancel_before_task_starts(tmp_path):
    async def run():
        store = Store(tmp_path)
        tid = uuid4().hex
        store.put({"id": tid, "status": "idle", "runs": [], "created_at": "now"})
        jobs = Jobs(store, tmp_path / "models")
        jobs.start(tid, "demucs-6")
        await jobs.cancel(tid)
        assert jobs.tasks == {}
        assert store.get(tid)["status"] == "idle"

    asyncio.run(run())


def test_cancel_running_process_retains_previous_results(tmp_path, monkeypatch):
    real_spawn = asyncio.create_subprocess_exec
    spawned = []

    async def fake_worker(*args, **kwargs):
        process = await real_spawn(
            sys.executable, "-c", "import time; print('started', flush=True); time.sleep(60)", **kwargs
        )
        spawned.append(process)
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_worker)

    async def run():
        store = Store(tmp_path)
        tid = uuid4().hex
        old = [{"id": "old", "stems": []}]
        store.put({"id": tid, "status": "ready", "runs": old, "created_at": "now"})
        jobs = Jobs(store, tmp_path / "models")
        jobs.start(tid, "demucs-6")
        for _ in range(100):
            if spawned:
                break
            await asyncio.sleep(0.01)
        assert spawned
        await jobs.cancel(tid)
        assert spawned[0].returncode is not None
        assert store.get(tid)["runs"] == old
        assert store.get(tid)["status"] == "ready"
        assert not jobs.tasks

    asyncio.run(run())
