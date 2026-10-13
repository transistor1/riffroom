import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import type { Mix, Model, Run, Stem, Track } from "../types";
import Mixer, {
  mixForStems,
  preserveStemMix,
  reloadMixerGraph,
  resolveEffectiveMixer,
} from "./Mixer";
import type { MixerEngine } from "../audio";

const stem = (name: string, runId: string): Stem => ({
  name,
  file: `${name}.wav`,
  url: `/api/tracks/track/audio/${runId}/${name}.wav`,
  peaks: [],
});

const root = (id: string, names: string[]): Run => ({
  id,
  take_number: id === "root-a" ? 1 : 2,
  model_id: "demucs-6",
  stems: names.map((name) => stem(name, id)),
});

const child = (
  id: string,
  parentId: string,
  parentStem: string,
  names: string[],
  splitNumber = 1,
): Run => ({
  id,
  split_number: splitNumber,
  model_id: "drumsep",
  source: { type: "stem", run_id: parentId, stem_name: parentStem },
  stems: names.map((name) => stem(name, id)),
});

const track = (runs: Run[]): Track => ({
  id: "track",
  title: "Track",
  filename: "track.wav",
  duration: 30,
  created_at: "now",
  status: "ready",
  message: "Ready",
  runs,
  active_run: "root-a",
  peaks: [],
  error: null,
});

describe("effective chained mixer", () => {
  it("recursively replaces parent stems instead of adding duplicate audio", () => {
    const rootA = root("root-a", ["guitar", "drums", "bass"]);
    const drums = child("drum-child", rootA.id, "drums", ["kick", "snare"]);
    const kick = child("kick-child", drums.id, "kick", ["attack", "body"]);
    rootA.active_children = { drums: drums.id };
    drums.active_children = { kick: kick.id };

    const result = resolveEffectiveMixer(track([rootA, drums, kick]), rootA);

    expect(result.stems.map((item) => item.displayName)).toEqual([
      "guitar",
      "attack",
      "body",
      "snare",
      "bass",
    ]);
    expect(result.stems.map((item) => item.displayName)).not.toContain("drums");
    expect(result.stems.map((item) => item.displayName)).not.toContain("kick");
    expect(new Set(result.stems.map((item) => item.name)).size).toBe(
      result.stems.length,
    );
  });

  it("collapses to the parent and can select a different sibling child", () => {
    const rootA = root("root-a", ["drums"]);
    const first = child("first", rootA.id, "drums", ["kick", "snare"], 1);
    const second = child(
      "second",
      rootA.id,
      "drums",
      ["percussion", "cymbals"],
      2,
    );
    const project = track([rootA, first, second]);

    expect(
      resolveEffectiveMixer(project, rootA).stems.map(
        (item) => item.displayName,
      ),
    ).toEqual(["drums"]);
    rootA.active_children = { drums: second.id };
    expect(
      resolveEffectiveMixer(project, rootA).stems.map(
        (item) => item.displayName,
      ),
    ).toEqual(["percussion", "cymbals"]);
    expect(
      resolveEffectiveMixer(project, rootA).expansions[0].children.map(
        (run) => run.id,
      ),
    ).toEqual(["first", "second"]);
  });

  it("never leaks a child expansion into another root take", () => {
    const rootA = root("root-a", ["drums"]);
    const rootB = root("root-b", ["drums"]);
    const drums = child("drum-child", rootA.id, "drums", ["kick", "snare"]);
    rootA.active_children = { drums: drums.id };
    const project = track([rootA, rootB, drums]);

    expect(
      resolveEffectiveMixer(project, rootA).stems.map(
        (item) => item.displayName,
      ),
    ).toEqual(["kick", "snare"]);
    expect(
      resolveEffectiveMixer(project, rootB).stems.map(
        (item) => item.displayName,
      ),
    ).toEqual(["drums"]);
    expect(resolveEffectiveMixer(project, rootB).expansions).toEqual([]);
  });

  it("preserves hidden parent and child channels across collapse and re-expand", () => {
    const rootA = root("root-a", ["drums"]);
    const drums = child("drum-child", rootA.id, "drums", ["kick", "snare"]);
    const project = track([rootA, drums]);
    let saved: Mix = {
      drums: { volume: 0.42, muted: true, solo: false },
    };

    rootA.active_children = { drums: drums.id };
    const expanded = resolveEffectiveMixer(project, rootA).stems;
    saved = preserveStemMix(saved, expanded);
    saved[`${drums.id}:kick`] = { volume: 1.37, muted: false, solo: true };

    rootA.active_children = {};
    saved = preserveStemMix(saved, resolveEffectiveMixer(project, rootA).stems);
    expect(mixForStems(saved, rootA.stems).drums).toEqual({
      volume: 0.42,
      muted: true,
      solo: false,
    });

    rootA.active_children = { drums: drums.id };
    expect(mixForStems(saved, resolveEffectiveMixer(project, rootA).stems)).toMatchObject({
      [`${drums.id}:kick`]: { volume: 1.37, muted: false, solo: true },
    });
  });

  it("uses the full catalog for saved split labels and visible models for new splits", () => {
    const rootA = root("root-a", ["drums"]);
    const drums = child("drum-child", rootA.id, "drums", ["kick"]);
    drums.model_id = "hidden-model";
    rootA.active_children = { drums: drums.id };
    const project = track([rootA, drums]);
    const model = (id: string, name: string) => ({ id, name }) as Model;

    vi.stubGlobal("localStorage", { getItem: () => null, setItem: () => {} });
    const html = renderToStaticMarkup(
      <Mixer
        track={project}
        run={rootA}
        models={[model("visible-model", "Visible model")]}
        modelCatalog={[
          model("visible-model", "Visible model"),
          model("hidden-model", "Friendly hidden model"),
        ]}
      />,
    );

    expect(html).toContain("Friendly hidden model · split 1");
    expect(html).toContain("Visible model");
    expect(html).not.toContain("hidden-model · split 1");
    vi.unstubAllGlobals();
  });

  it("reloads a changed child graph on the same engine and restores position", async () => {
    const loaded: string[][] = [];
    const seeks: number[] = [];
    const setRate = vi.fn();
    const setPitch = vi.fn();
    const setMaster = vi.fn();
    const setLoopPlan = vi.fn();
    const player = {
      duration: 30,
      setMix() {},
      async load(stems: Stem[]) {
        loaded.push(stems.map((item) => item.url));
      },
      seek(position: number) {
        seeks.push(position);
      },
      rate: 0.75,
      pitchSemitones: 2,
      setRate,
      setPitch,
      setMaster,
      setLoopPlan,
    } as unknown as MixerEngine;
    const first = [stem("kick", "first-child")];
    const second = [stem("kick", "second-child")];

    await reloadMixerGraph(player, first, {}, new AbortController().signal, 12.5);
    await reloadMixerGraph(player, second, {}, new AbortController().signal, 12.5);

    expect(loaded).toEqual([[first[0].url], [second[0].url]]);
    expect(seeks).toEqual([12.5, 12.5]);
    expect(player.rate).toBe(0.75);
    expect(player.pitchSemitones).toBe(2);
    expect(setRate).not.toHaveBeenCalled();
    expect(setPitch).not.toHaveBeenCalled();
    expect(setMaster).not.toHaveBeenCalled();
    expect(setLoopPlan).not.toHaveBeenCalled();
  });
});
