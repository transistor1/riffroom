import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import {
  deleteRunAndRefresh,
  mixerMountKey,
  PORTABLE_RUNTIME_POLL_MS,
  PortableRuntimeInstallProgress,
  removeRunFromState,
  schedulePortableRuntimePoll,
  separationRunLabel,
  selectedRunFor,
} from "./App";
import type { RuntimeStatus, Track } from "./types";

const runtimeStatus = (
  changes: Partial<RuntimeStatus> = {},
): RuntimeStatus => ({
  id: "audio-separator",
  display_name: "Portable audio-separator runtime",
  version: "0.47.0",
  available: false,
  managed_installed: false,
  installing: true,
  install_phase: "Installing CUDA-enabled PyTorch",
  install_started_at: "2026-10-12T16:00:00+00:00",
  error: null,
  compute_backend: null,
  compute_device: null,
  ...changes,
});

const trackWithRuns = (): Track => ({
  id: "track-1",
  title: "Track",
  filename: "track.wav",
  duration: 30,
  created_at: "2026-10-12T16:00:00+00:00",
  status: "ready",
  message: "Ready",
  active_run: "run-2",
  runs: ["run-1", "run-2", "run-3"].map((id, index) => ({
    id,
    take_number: index + 1,
    model_id: "demucs-6",
    stems: [
      {
        name: "drums",
        file: "drums.wav",
        url: `/api/tracks/track-1/audio/${id}/drums.wav`,
        peaks: [],
      },
    ],
  })),
  peaks: [],
  error: null,
});

describe("portable runtime installation status", () => {
  it("renders the current safe phase and elapsed time", () => {
    const html = renderToStaticMarkup(
      <PortableRuntimeInstallProgress
        status={runtimeStatus()}
        now={Date.parse("2026-10-12T16:01:05+00:00")}
      />,
    );

    expect(html).toContain("Installing CUDA-enabled PyTorch");
    expect(html).toContain("1m 05s elapsed");
    expect(html).not.toContain("pip install");
    expect(html).not.toContain("C:\\");
  });

  it("polls while installation is active and refreshes models when ready", async () => {
    let callback: (() => void) | undefined;
    const refreshStatus = vi.fn(async () =>
      runtimeStatus({ installing: false, available: true }),
    );
    const refreshModels = vi.fn(async () => {});
    const reportError = vi.fn();

    const timer = schedulePortableRuntimePoll(
      runtimeStatus(),
      refreshStatus,
      refreshModels,
      reportError,
      (next, delay) => {
        expect(delay).toBe(PORTABLE_RUNTIME_POLL_MS);
        callback = next;
        return 42;
      },
    );
    expect(timer).toBe(42);
    callback?.();
    await vi.waitFor(() => expect(refreshModels).toHaveBeenCalledOnce());
    expect(refreshStatus).toHaveBeenCalledOnce();
    expect(reportError).not.toHaveBeenCalled();
    expect(
      schedulePortableRuntimePoll(
        runtimeStatus({ installing: false }),
        refreshStatus,
        refreshModels,
        reportError,
      ),
    ).toBeUndefined();
  });
});

describe("selected separation deletion", () => {
  it("deletes the selected middle run without surfacing an error", async () => {
    const current = trackWithRuns();
    const next = removeRunFromState([current], current.id, "run-2", {
      kind: "run",
      trackId: current.id,
      runId: "run-2",
    });
    const nextTrack = next.tracks[0];
    const selected = selectedRunFor(nextTrack, next.runId);
    const requestedStemUrls = selected?.stems.map((stem) => stem.url) ?? [];

    expect(next.runId).toBe("run-3");
    expect(nextTrack.active_run).toBe("run-3");
    expect(nextTrack.runs.map((run) => run.id)).toEqual(["run-1", "run-3"]);
    expect(nextTrack.runs.map((run) => run.take_number)).toEqual([1, 3]);
    expect(selected?.id).toBe("run-3");
    expect(selected?.take_number).toBe(3);
    expect(selected && separationRunLabel(selected, [])).toBe(
      "demucs-6 · take 3",
    );
    expect(requestedStemUrls).toEqual([
      "/api/tracks/track-1/audio/run-3/drums.wav",
    ]);
    expect(requestedStemUrls.some((url) => url.includes("run-2"))).toBe(false);

    const requests: Array<{ path: string; method: string }> = [];
    const refresh = vi.fn(async () => {
      requests.push({ path: "/tracks", method: "GET" });
    });
    const removeStoredMix = vi.fn();
    let surfacedError = "";
    try {
      await deleteRunAndRefresh(
        { kind: "run", trackId: current.id, runId: "run-2" },
        refresh,
        async (path, options) => {
          requests.push({ path, method: options?.method ?? "GET" });
        },
        removeStoredMix,
      );
    } catch (error) {
      surfacedError = (error as Error).message;
    }

    expect(surfacedError).toBe("");
    expect(refresh).toHaveBeenCalledOnce();
    expect(removeStoredMix).toHaveBeenCalledWith("riffroom:mix:track-1:run-2");
    expect(requests).toEqual([
      { path: "/tracks/track-1/runs/run-2", method: "DELETE" },
      { path: "/tracks", method: "GET" },
    ]);
    expect(
      requests.filter(
        ({ path, method }) => path.includes("run-2") && method !== "DELETE",
      ),
    ).toEqual([]);
  });

  it("switches to Original mix when the selected run is the last run", () => {
    const current = trackWithRuns();
    current.runs = [current.runs[1]];
    const next = removeRunFromState([current], current.id, null, {
      kind: "run",
      trackId: current.id,
      runId: "run-2",
    });

    expect(next.runId).toBe("original");
    expect(next.tracks[0].active_run).toBeNull();
    expect(next.tracks[0].runs).toEqual([]);
    expect(selectedRunFor(next.tracks[0], next.runId)).toBeUndefined();
  });
});

describe("mixer lifecycle", () => {
  it("keeps the same mount across expansion changes but not root-take changes", () => {
    const current = trackWithRuns();
    const first = current.runs[0];
    const second = current.runs[1];
    const before = mixerMountKey(current.id, first);

    first.active_children = { drums: "child-a" };

    expect(mixerMountKey(current.id, first)).toBe(before);
    expect(mixerMountKey(current.id, second)).not.toBe(before);
    expect(mixerMountKey(current.id)).toBe(`${current.id}:original`);
  });
});
