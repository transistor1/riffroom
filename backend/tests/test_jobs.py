import asyncio
import json
import signal
import sys
import threading
from pathlib import Path
from uuid import uuid4

from riffroom.jobs import Jobs, _process_group_kwargs
from riffroom.models import PORTABLE_DRUMSEP_FILENAME, community_model_id
from riffroom.store import Store


class AvailableProvider:
    def is_available(self):
        return True


def add_original(store, track_id):
    (store.directory(track_id) / "original.wav").touch()


class FakeProcess:
    def __init__(self, timeout=False):
        self.pid = 123
        self.returncode = None
        self.timeout = timeout
        self.signals = []
        self.terminated = 0
        self.killed = 0
        self.waits = 0

    def send_signal(self, event):
        self.signals.append(event)

    def terminate(self):
        self.terminated += 1

    def kill(self):
        self.killed += 1

    async def wait(self):
        self.waits += 1
        if self.timeout and self.waits == 1:
            raise asyncio.TimeoutError
        self.returncode = -1
        return self.returncode


def test_process_group_spawn_kwargs_are_platform_aware(monkeypatch):
    monkeypatch.setattr("riffroom.jobs.subprocess.CREATE_NEW_PROCESS_GROUP", 0x200, raising=False)

    assert _process_group_kwargs("posix") == {"start_new_session": True}
    assert _process_group_kwargs("nt") == {"creationflags": 0x200}


def test_windows_graceful_stop_uses_ctrl_break(tmp_path, monkeypatch):
    async def run():
        ctrl_break = 1
        process = FakeProcess()
        jobs = Jobs(Store(tmp_path), tmp_path / "models")
        jobs.processes["track"] = process
        monkeypatch.setattr("riffroom.jobs.signal.CTRL_BREAK_EVENT", ctrl_break, raising=False)
        monkeypatch.setattr("riffroom.jobs.os.killpg", lambda *_: None)

        await jobs._kill("track", platform="nt")

        assert process.signals == [ctrl_break]
        assert process.terminated == 0
        assert process.killed == 0
        assert process.waits == 1

    asyncio.run(run())


def test_windows_timeout_falls_back_to_kill_without_killpg(tmp_path, monkeypatch):
    async def run():
        process = FakeProcess(timeout=True)
        jobs = Jobs(Store(tmp_path), tmp_path / "models")
        jobs.processes["track"] = process

        def unexpected_killpg(*_):
            raise AssertionError("Windows cleanup must not call os.killpg")

        monkeypatch.setattr("riffroom.jobs.os.killpg", unexpected_killpg)
        await jobs._kill("track", platform="nt", ctrl_break_event=None)

        assert process.terminated == 1
        assert process.killed == 1
        assert process.waits == 2

    asyncio.run(run())


def test_posix_stop_uses_process_group_signals(tmp_path, monkeypatch):
    async def run():
        process = FakeProcess(timeout=True)
        jobs = Jobs(Store(tmp_path), tmp_path / "models")
        jobs.processes["track"] = process
        signals = []
        monkeypatch.setattr("riffroom.jobs.os.killpg", lambda pid, event: signals.append((pid, event)))

        await jobs._kill("track", platform="posix")

        assert signals == [(process.pid, signal.SIGTERM), (process.pid, signal.SIGKILL)]
        assert process.killed == 0
        assert process.waits == 2

    asyncio.run(run())


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
        add_original(store, tid)
        jobs = Jobs(store, tmp_path / "models")
        jobs.start(tid, "demucs-6")
        await jobs.cancel(tid)
        assert jobs.tasks == {}
        assert store.get(tid)["status"] == "idle"

    asyncio.run(run())


def test_start_serializes_source_validation_with_activation(tmp_path, monkeypatch):
    async def run():
        store = Store(tmp_path / "tracks")
        tid, run_id = uuid4().hex, uuid4().hex
        run_folder = store.directory(tid) / "runs" / run_id
        run_folder.mkdir(parents=True)
        (run_folder / "drums.wav").touch()
        store.put(
            {
                "id": tid,
                "status": "ready",
                "runs": [
                    {
                        "id": run_id,
                        "take_number": 1,
                        "model_id": "demucs-6",
                        "stems": [{"name": "drums", "file": "drums.wav"}],
                    }
                ],
                "active_run": run_id,
                "created_at": "now",
            }
        )
        jobs = Jobs(store, tmp_path / "models")
        source = {"type": "stem", "run_id": run_id, "stem_name": "drums"}
        real_source_path = jobs._source_path
        delete_started = threading.Event()
        delete_finished = threading.Event()

        def try_delete_source():
            delete_started.set()
            with store.lock:
                track = store.get(tid)
                if track["status"] not in {"queued", "processing"}:
                    track["runs"] = [run for run in track["runs"] if run["id"] != run_id]
                    store.put(track)
            delete_finished.set()

        def source_path_while_delete_waits(track_id, selected_source):
            path = real_source_path(track_id, selected_source)
            thread = threading.Thread(target=try_delete_source)
            thread.start()
            assert delete_started.wait(1)
            assert not delete_finished.wait(0.05)
            return path

        monkeypatch.setattr(jobs, "_source_path", source_path_while_delete_waits)
        jobs.start(tid, "demucs-6", source)

        assert delete_finished.wait(1)
        queued = store.get(tid)
        assert queued["status"] == "queued"
        assert queued["pending_source"] == source
        assert [run["id"] for run in queued["runs"]] == [run_id]
        await jobs.cancel(tid)

    asyncio.run(run())


def test_store_backfills_legacy_take_numbers_once_in_run_order(tmp_path):
    store = Store(tmp_path)
    tid = uuid4().hex
    folder = store.directory(tid)
    folder.mkdir()
    manifest = folder / "track.json"
    manifest.write_text(
        json.dumps(
            {
                "id": tid,
                "status": "ready",
                "created_at": "now",
                "runs": [
                    {"id": "first", "stems": []},
                    {"id": "second", "stems": []},
                    {"id": "third", "stems": []},
                ],
            }
        )
    )

    migrated = store.get(tid)

    assert [run["take_number"] for run in migrated["runs"]] == [1, 2, 3]
    assert migrated["next_take_number"] == 4
    assert json.loads(manifest.read_text()) == migrated
    assert store.get(tid) == migrated


def test_store_treats_legacy_runs_as_roots_without_numbering_children(tmp_path):
    store = Store(tmp_path)
    tid = uuid4().hex
    folder = store.directory(tid)
    folder.mkdir()
    (folder / "track.json").write_text(
        json.dumps(
            {
                "id": tid,
                "status": "ready",
                "created_at": "now",
                "runs": [
                    {"id": "legacy-root", "stems": []},
                    {
                        "id": "child",
                        "source": {
                            "type": "stem",
                            "run_id": "legacy-root",
                            "stem_name": "drums",
                        },
                        "stems": [],
                    },
                    {"id": "second-legacy-root", "stems": []},
                ],
            }
        )
    )

    migrated = store.get(tid)

    assert migrated["runs"][0]["take_number"] == 1
    assert "take_number" not in migrated["runs"][1]
    assert migrated["runs"][2]["take_number"] == 2
    assert migrated["next_take_number"] == 3


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
        add_original(store, tid)
        jobs = Jobs(
            store,
            tmp_path / "models",
            provider_registry={"mlx-audio-separator": AvailableProvider()},
        )
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


def test_cleanup_failure_does_not_replace_separator_error(tmp_path, monkeypatch):
    async def failed_worker(*args, **kwargs):
        raise RuntimeError("original separator error")

    async def failed_cleanup(track_id):
        raise RuntimeError("secondary cleanup error")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", failed_worker)

    async def run():
        store = Store(tmp_path / "tracks")
        tid = uuid4().hex
        store.put({"id": tid, "status": "idle", "runs": [], "created_at": "now"})
        add_original(store, tid)
        jobs = Jobs(store, tmp_path / "models")
        monkeypatch.setattr(jobs, "_provider_available", lambda provider_id: True)
        monkeypatch.setattr(jobs, "_kill", failed_cleanup)

        jobs.start(tid, "demucs-6")
        task = jobs.tasks[tid]
        await task

        track = store.get(tid)
        assert track["status"] == "error"
        assert track["error"] == "original separator error"

    asyncio.run(run())


def test_successful_job_stores_resolved_provider_id(tmp_path, monkeypatch):
    spawned = []

    class EmptyOutput:
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

    class SuccessfulProcess:
        stdout = EmptyOutput()
        returncode = 0

        async def wait(self):
            return 0

    async def fake_worker(*args, **kwargs):
        spawned.append(args)
        output = Path(args[4])
        (output / "stems.json").write_text(json.dumps([]))
        return SuccessfulProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_worker)

    async def run():
        store = Store(tmp_path / "tracks")
        tid = uuid4().hex
        store.put({"id": tid, "status": "idle", "runs": [], "created_at": "now"})
        add_original(store, tid)
        jobs = Jobs(
            store,
            tmp_path / "models",
            provider_registry={
                "mlx-audio-separator": AvailableProvider(),
                "audio-separator": AvailableProvider(),
            },
        )

        jobs.start(tid, "demucs-6")
        await jobs.tasks[tid]

        run_metadata = store.get(tid)["runs"][0]
        assert run_metadata["model_id"] == "demucs-6"
        assert run_metadata["provider_id"] == "mlx-audio-separator"
        assert run_metadata["source"] == {"type": "original"}
        assert spawned[0][3] == str(store.directory(tid) / "original.wav")
        assert spawned[0][6:] == ("demucs-6", "mlx-audio-separator")

        portable_track = uuid4().hex
        store.put({"id": portable_track, "status": "idle", "runs": [], "created_at": "now"})
        add_original(store, portable_track)
        portable_id = community_model_id(PORTABLE_DRUMSEP_FILENAME)
        jobs.start(portable_track, portable_id)
        await jobs.tasks[portable_track]

        portable_run = store.get(portable_track)["runs"][0]
        assert portable_run["model_id"] == portable_id
        assert portable_run["provider_id"] == "audio-separator"
        assert spawned[1][6:] == (portable_id, "audio-separator")

    asyncio.run(run())


def test_child_jobs_use_parent_audio_and_support_recursive_lineage(tmp_path, monkeypatch):
    spawned = []

    class EmptyOutput:
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

    class SuccessfulProcess:
        stdout = EmptyOutput()
        returncode = 0

        async def wait(self):
            return 0

    async def fake_worker(*args, **kwargs):
        spawned.append(args)
        output = Path(args[4])
        (output / "part.wav").touch()
        (output / "stems.json").write_text(
            json.dumps([{"name": "part", "file": "part.wav", "peaks": []}])
        )
        return SuccessfulProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_worker)

    async def run():
        store = Store(tmp_path / "tracks")
        tid, root_id = uuid4().hex, uuid4().hex
        root_folder = store.directory(tid) / "runs" / root_id
        root_folder.mkdir(parents=True)
        (root_folder / "drums.wav").touch()
        store.put(
            {
                "id": tid,
                "status": "ready",
                "created_at": "now",
                "runs": [
                    {
                        "id": root_id,
                        "take_number": 1,
                        "model_id": "demucs-6",
                        "stems": [{"name": "drums", "file": "drums.wav"}],
                    }
                ],
                "active_run": root_id,
                "next_take_number": 2,
            }
        )
        jobs = Jobs(
            store,
            tmp_path / "models",
            provider_registry={"mlx-audio-separator": AvailableProvider()},
        )
        first_source = {"type": "stem", "run_id": root_id, "stem_name": "drums"}
        jobs.start(tid, "demucs-6", first_source)
        await jobs.tasks[tid]
        first_child = store.get(tid)["runs"][-1]
        second_source = {"type": "stem", "run_id": first_child["id"], "stem_name": "part"}
        jobs.start(tid, "demucs-6", second_source)
        await jobs.tasks[tid]
        track = store.get(tid)
        second_child = track["runs"][-1]
        jobs.start(tid, "demucs-6", first_source)
        await jobs.tasks[tid]
        track = store.get(tid)
        sibling_child = track["runs"][-1]

        assert Path(spawned[0][3]) == root_folder / "drums.wav"
        assert Path(spawned[1][3]) == store.directory(tid) / "runs" / first_child["id"] / "part.wav"
        assert Path(spawned[2][3]) == root_folder / "drums.wav"
        assert first_child["source"] == first_source
        assert second_child["source"] == second_source
        assert first_child["split_number"] == second_child["split_number"] == 1
        assert sibling_child["split_number"] == 2
        assert "take_number" not in first_child
        assert "take_number" not in second_child
        assert "take_number" not in sibling_child
        assert track["runs"][0]["active_children"] == {"drums": sibling_child["id"]}
        assert track["runs"][0]["next_split_numbers"] == {"drums": 3}
        assert track["runs"][1]["active_children"] == {"part": second_child["id"]}
        assert track["active_run"] == root_id
        assert track["next_take_number"] == 2

    asyncio.run(run())


def test_successful_job_keeps_gap_and_uses_persisted_next_take_number(tmp_path, monkeypatch):
    class EmptyOutput:
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

    class SuccessfulProcess:
        stdout = EmptyOutput()
        returncode = 0

        async def wait(self):
            return 0

    async def fake_worker(*args, **kwargs):
        output = Path(args[4])
        (output / "stems.json").write_text(json.dumps([]))
        return SuccessfulProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_worker)

    async def run():
        store = Store(tmp_path / "tracks")
        tid = uuid4().hex
        store.put(
            {
                "id": tid,
                "status": "ready",
                "created_at": "now",
                "runs": [{"id": f"run-{take}", "take_number": take, "stems": []} for take in [1, 2, 4, 5]],
                "next_take_number": 6,
            }
        )
        add_original(store, tid)
        jobs = Jobs(
            store,
            tmp_path / "models",
            provider_registry={"mlx-audio-separator": AvailableProvider()},
        )

        jobs.start(tid, "demucs-6")
        await jobs.tasks[tid]

        track = store.get(tid)
        assert [run["take_number"] for run in track["runs"]] == [1, 2, 4, 5, 6]
        assert track["runs"][-1]["id"] == track["active_run"]
        assert track["next_take_number"] == 7

    asyncio.run(run())
