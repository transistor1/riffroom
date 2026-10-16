import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { BeatAnalysis, BeatGrid, Mix, Model, Run, Stem, Track } from "../types";
import Mixer, {
  applyManualChannelChange,
  derivePerformanceParts,
  isPerformancePartAvailable,
  loadPerformancePartPreference,
  mixForStems,
  noPerformanceShortcut,
  performancePartCopy,
  performancePartPreferenceKey,
  preserveStemMix,
  reloadMixerGraph,
  retargetPerformanceShortcut,
  resolveEffectiveMixer,
  restorePerformanceShortcut,
  savePerformancePartPreference,
  transitionPerformanceShortcut,
} from "./Mixer";
import { MixerEngine } from "../audio";
import { correctionPreferenceKey, type BeatCorrection } from "../beatCorrection";

// Exercise Mixer itself without a DOM or a React renderer. Selected effects
// (including engine creation for playback preferences) are stepped below. This checks real
// closures/dependencies, not React's lifecycle, cleanup ordering, or remounts.
const hookHarness = vi.hoisted(() => ({ current: null as any }));
vi.mock("react", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react")>();
  return {
    ...actual,
    useState: (initial: any) => {
      const harness = hookHarness.current;
      if (!harness) return actual.useState(initial);
      const slot = harness.stateCursor++;
      if (!(slot in harness.states)) {
        harness.states[slot] = typeof initial === "function" ? initial() : initial;
      }
      return [harness.states[slot], (next: any) => {
        harness.states[slot] = typeof next === "function" ? next(harness.states[slot]) : next;
      }];
    },
    useRef: (initial: any) => {
      const harness = hookHarness.current;
      if (!harness) return actual.useRef(initial);
      const slot = harness.refCursor++;
      harness.refs[slot] ??= { current: slot === 0 ? harness.player : initial };
      return harness.refs[slot];
    },
    useCallback: (callback: any, deps: any) => hookHarness.current
      ? callback : actual.useCallback(callback, deps),
    useEffect: (callback: any, deps: any) => {
      const harness = hookHarness.current;
      if (!harness) return actual.useEffect(callback, deps);
      harness.effects.push({ callback, deps });
    },
  };
});

afterEach(() => {
  hookHarness.current = null;
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

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

const memoryStorage = () => {
  const values = new Map<string, string>();
  return {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => values.set(key, value),
    values,
  };
};

describe("performance part shortcuts", () => {
  it("derives choices from top-level stems and filters generic stems", () => {
    const rootA = root("root-a", [
      "vocals",
      "guitar",
      "drums",
      "other",
      "instrumental",
      "music",
      "no-vocals",
      "karaoke",
    ]);

    expect(derivePerformanceParts(rootA)).toEqual([
      "vocals",
      "guitar",
      "drums",
    ]);
  });

  it("propagates root logical identity through nested descendants", () => {
    const rootA = root("root-a", ["drums", "bass"]);
    const drums = child("drum-child", rootA.id, "drums", ["kick", "snare"]);
    const kick = child("kick-child", drums.id, "kick", ["attack", "body"]);
    rootA.active_children = { drums: drums.id };
    drums.active_children = { kick: kick.id };

    const effective = resolveEffectiveMixer(track([rootA, drums, kick]), rootA);

    expect(
      effective.stems.map(({ displayName, logicalPart }) => ({
        displayName,
        logicalPart,
      })),
    ).toEqual([
      { displayName: "attack", logicalPart: "drums" },
      { displayName: "body", logicalPart: "drums" },
      { displayName: "snare", logicalPart: "drums" },
      { displayName: "bass", logicalPart: "bass" },
    ]);
  });

  it("mutes every active descendant of the selected family only", () => {
    const rootA = root("root-a", ["guitar", "drums", "bass"]);
    const guitar = child("guitar-child", rootA.id, "guitar", [
      "lead",
      "rhythm",
    ]);
    rootA.active_children = { guitar: guitar.id };
    const effective = resolveEffectiveMixer(
      track([rootA, guitar]),
      rootA,
    ).stems;

    const original = mixForStems({}, effective);
    const { mix } = transitionPerformanceShortcut(
      original,
      effective,
      noPerformanceShortcut(),
      "play-with-band",
      "guitar",
    );

    expect(mix[`${guitar.id}:lead`]).toEqual({
      volume: 1,
      muted: true,
      solo: false,
    });
    expect(mix[`${guitar.id}:rhythm`].muted).toBe(true);
    expect(mix.drums.muted).toBe(false);
    expect(mix.bass.muted).toBe(false);
  });

  it("solos the same complete selected logical family", () => {
    const rootA = root("root-a", ["drums", "vocals"]);
    const drums = child("drum-child", rootA.id, "drums", ["kick", "snare"]);
    rootA.active_children = { drums: drums.id };
    const effective = resolveEffectiveMixer(track([rootA, drums]), rootA).stems;

    const original = mixForStems({}, effective);
    const { mix } = transitionPerformanceShortcut(
      original,
      effective,
      noPerformanceShortcut(),
      "hear-just",
      "drums",
    );

    expect(mix[`${drums.id}:kick`].solo).toBe(true);
    expect(mix[`${drums.id}:snare`].solo).toBe(true);
    expect(mix.vocals.solo).toBe(false);
    expect(Object.values(mix).every((channel) => !channel.muted)).toBe(true);
  });

  it("keeps primary and secondary wording synchronized, including vocals", () => {
    expect(performancePartCopy("vocals")).toEqual({
      primary: "Sing with the band",
      secondary: "Hear just the vocals",
    });
    expect(performancePartCopy("piano")).toEqual({
      primary: "Play piano with the band",
      secondary: "Hear just the piano",
    });
  });

  it("renders synchronized vocals wording on both preset buttons", () => {
    const rootA = root("root-a", ["vocals", "drums"]);
    const project = track([rootA]);
    vi.stubGlobal("localStorage", {
      getItem: (key: string) =>
        key === performancePartPreferenceKey(project.id) ? "vocals" : null,
      setItem: () => {},
    });

    const html = renderToStaticMarkup(<Mixer track={project} run={rootA} />);

    expect(html).toContain("Sing with the band");
    expect(html).toContain("Hear just the vocals");
    vi.unstubAllGlobals();
  });

  it("keeps a per-song preference across takes without replacing an unavailable choice", () => {
    const storage = memoryStorage();
    const firstTakeParts = derivePerformanceParts(
      root("root-a", ["vocals", "guitar", "drums"]),
    );
    const secondTakeParts = derivePerformanceParts(
      root("root-b", ["guitar", "vocals", "drums"]),
    );
    const unavailableTakeParts = derivePerformanceParts(
      root("root-c", ["vocals", "drums"]),
    );

    expect(
      loadPerformancePartPreference("song-1", firstTakeParts, storage),
    ).toBe("guitar");
    expect(
      loadPerformancePartPreference("song-1", secondTakeParts, storage),
    ).toBe("guitar");
    expect(isPerformancePartAvailable("guitar", secondTakeParts)).toBe(true);
    expect(
      loadPerformancePartPreference("song-1", unavailableTakeParts, storage),
    ).toBe("guitar");
    expect(isPerformancePartAvailable("guitar", unavailableTakeParts)).toBe(
      false,
    );
    expect(storage.values.get(performancePartPreferenceKey("song-1"))).toBe(
      "guitar",
    );
  });

  it("uses a stored preference when available and updates both presets after an explicit choice", () => {
    const storage = memoryStorage();
    const rootA = root("root-a", ["vocals", "guitar", "drums"]);
    const parts = derivePerformanceParts(rootA);
    savePerformancePartPreference("song-1", "vocals", storage);

    expect(loadPerformancePartPreference("song-1", parts, storage)).toBe(
      "vocals",
    );
    expect(isPerformancePartAvailable("vocals", parts)).toBe(true);

    savePerformancePartPreference("song-1", "drums", storage);
    const selected = loadPerformancePartPreference("song-1", parts, storage)!;
    const effective = resolveEffectiveMixer(track([rootA]), rootA).stems;

    expect(selected).toBe("drums");
    expect(performancePartCopy(selected)).toEqual({
      primary: "Play drums with the band",
      secondary: "Hear just the drums",
    });
    const original = mixForStems({}, effective);
    expect(
      transitionPerformanceShortcut(
        original,
        effective,
        noPerformanceShortcut(),
        "play-with-band",
        selected,
      ).mix.drums.muted,
    ).toBe(true);
    expect(
      transitionPerformanceShortcut(
        original,
        effective,
        noPerformanceShortcut(),
        "hear-just",
        selected,
      ).mix.drums.solo,
    ).toBe(true);
  });

  it("retargets play-with-band and keeps its explicit mode active", () => {
    const rootA = root("root-a", ["guitar", "vocals", "drums"]);
    const effective = resolveEffectiveMixer(track([rootA]), rootA).stems;
    const original: Mix = {
      guitar: { volume: 0.71, muted: false, solo: true },
      vocals: { volume: 1.22, muted: false, solo: false },
      drums: { volume: 0.43, muted: false, solo: true },
    };
    const active = transitionPerformanceShortcut(
      original,
      effective,
      noPerformanceShortcut(),
      "play-with-band",
      "guitar",
    );

    const retargeted = retargetPerformanceShortcut(
      active.mix,
      effective,
      active.shortcut,
      "vocals",
    );

    expect(retargeted.mix.guitar).toEqual(original.guitar);
    expect(retargeted.mix.vocals).toEqual({
      ...original.vocals,
      muted: true,
    });
    expect(retargeted.mix.drums).toEqual(original.drums);
    expect(retargeted.shortcut).toMatchObject({
      mode: "play-with-band",
      part: "vocals",
    });
    expect(performancePartCopy(retargeted.shortcut.part!).primary).toBe(
      "Sing with the band",
    );
  });

  it("changes only the preference when no shortcut is active", () => {
    const rootA = root("root-a", ["guitar", "vocals"]);
    const effective = resolveEffectiveMixer(track([rootA]), rootA).stems;
    const original: Mix = {
      guitar: { volume: 0.62, muted: true, solo: false },
      vocals: { volume: 1.41, muted: false, solo: true },
    };

    const retargeted = retargetPerformanceShortcut(
      original,
      effective,
      noPerformanceShortcut(),
      "vocals",
    );

    expect(retargeted.mix).toBe(original);
    expect(retargeted.shortcut.mode).toBe("none");
  });

  it("restores exact family mutes without touching other mix fields", () => {
    const rootA = root("root-a", ["guitar", "drums"]);
    const guitar = child("guitar-child", rootA.id, "guitar", [
      "lead",
      "rhythm",
    ]);
    rootA.active_children = { guitar: guitar.id };
    const effective = resolveEffectiveMixer(track([rootA, guitar]), rootA).stems;
    const original: Mix = {
      [`${guitar.id}:lead`]: { volume: 0.4, muted: true, solo: true },
      [`${guitar.id}:rhythm`]: { volume: 1.6, muted: false, solo: false },
      drums: { volume: 0.8, muted: true, solo: true },
    };
    const active = transitionPerformanceShortcut(
      original,
      effective,
      noPerformanceShortcut(),
      "play-with-band",
      "guitar",
    );
    const off = transitionPerformanceShortcut(
      active.mix,
      effective,
      active.shortcut,
      "none",
      "guitar",
    );

    expect(active.mix[`${guitar.id}:lead`].muted).toBe(true);
    expect(active.mix[`${guitar.id}:rhythm`].muted).toBe(true);
    expect(off.mix).toEqual(original);
    expect(off.shortcut.mode).toBe("none");
  });

  it("temporarily unmutes a muted hear-just family and restores it", () => {
    const rootA = root("root-a", ["guitar", "vocals", "drums"]);
    const effective = resolveEffectiveMixer(track([rootA]), rootA).stems;
    const original: Mix = {
      guitar: { volume: 0.5, muted: true, solo: false },
      vocals: { volume: 1.5, muted: false, solo: true },
      drums: { volume: 0.9, muted: true, solo: true },
    };
    const active = transitionPerformanceShortcut(
      original,
      effective,
      noPerformanceShortcut(),
      "hear-just",
      "guitar",
    );
    const off = transitionPerformanceShortcut(
      active.mix,
      effective,
      active.shortcut,
      "none",
      "guitar",
    );

    expect(active.mix).toEqual({
      guitar: { ...original.guitar, muted: false, solo: true },
      vocals: { ...original.vocals, solo: false },
      drums: { ...original.drums, solo: false },
    });
    expect(off.mix).toEqual(original);
  });

  it("restores each overlay before switching play to hear-just and back", () => {
    const rootA = root("root-a", ["guitar", "vocals", "drums"]);
    const effective = resolveEffectiveMixer(track([rootA]), rootA).stems;
    const original: Mix = {
      guitar: { volume: 0.7, muted: false, solo: false },
      vocals: { volume: 1.2, muted: true, solo: true },
      drums: { volume: 0.6, muted: false, solo: false },
    };
    const play = transitionPerformanceShortcut(
      original,
      effective,
      noPerformanceShortcut(),
      "play-with-band",
      "guitar",
    );
    const hear = transitionPerformanceShortcut(
      play.mix,
      effective,
      play.shortcut,
      "hear-just",
      "guitar",
    );
    const playAgain = transitionPerformanceShortcut(
      hear.mix,
      effective,
      hear.shortcut,
      "play-with-band",
      "guitar",
    );
    const off = transitionPerformanceShortcut(
      playAgain.mix,
      effective,
      playAgain.shortcut,
      "none",
      "guitar",
    );

    expect(hear.mix.guitar.muted).toBe(original.guitar.muted);
    expect(hear.mix.vocals.solo).toBe(false);
    expect(playAgain.mix.vocals.solo).toBe(original.vocals.solo);
    expect(playAgain.mix.guitar.muted).toBe(true);
    expect(off.mix).toEqual(original);
  });

  it("retargets hear-just across every chained family descendant", () => {
    const rootA = root("root-a", ["drums", "vocals"]);
    const drums = child("drum-child", rootA.id, "drums", ["kick", "snare"]);
    const kick = child("kick-child", drums.id, "kick", ["attack", "body"]);
    rootA.active_children = { drums: drums.id };
    drums.active_children = { kick: kick.id };
    const effective = resolveEffectiveMixer(
      track([rootA, drums, kick]),
      rootA,
    ).stems;
    const original = mixForStems({}, effective);
    const drumsOnly = transitionPerformanceShortcut(
      original,
      effective,
      noPerformanceShortcut(),
      "hear-just",
      "drums",
    );
    const vocalsOnly = retargetPerformanceShortcut(
      drumsOnly.mix,
      effective,
      drumsOnly.shortcut,
      "vocals",
    );

    expect(
      effective
        .filter((item) => item.logicalPart === "drums")
        .every((item) => drumsOnly.mix[item.name].solo),
    ).toBe(true);
    expect(
      effective
        .filter((item) => item.logicalPart === "drums")
        .every((item) => !vocalsOnly.mix[item.name].solo),
    ).toBe(true);
    expect(vocalsOnly.mix.vocals.solo).toBe(true);
    expect(vocalsOnly.shortcut.mode).toBe("hear-just");
  });

  it("reconciles an active overlay when the effective graph changes", () => {
    const rootA = root("root-a", ["guitar", "drums"]);
    const guitar = child("guitar-child", rootA.id, "guitar", ["lead"]);
    const project = track([rootA, guitar]);
    const collapsed = resolveEffectiveMixer(project, rootA).stems;
    const original: Mix = {
      guitar: { volume: 0.8, muted: false, solo: false },
      drums: { volume: 1.3, muted: true, solo: true },
      [`${guitar.id}:lead`]: { volume: 0.6, muted: false, solo: true },
    };
    const active = transitionPerformanceShortcut(
      original,
      collapsed,
      noPerformanceShortcut(),
      "play-with-band",
      "guitar",
    );
    rootA.active_children = { guitar: guitar.id };
    const expanded = resolveEffectiveMixer(project, rootA).stems;
    const reconciled = retargetPerformanceShortcut(
      active.mix,
      expanded,
      active.shortcut,
      "guitar",
    );

    expect(reconciled.mix.guitar).toEqual(original.guitar);
    expect(reconciled.mix[`${guitar.id}:lead`]).toEqual({
      ...original[`${guitar.id}:lead`],
      muted: true,
    });
    expect(reconciled.mix.drums).toEqual(original.drums);
    expect(restorePerformanceShortcut(reconciled.mix, reconciled.shortcut)).toEqual(
      original,
    );
  });

  it("restores the hear-just baseline before applying a manual override", () => {
    const rootA = root("root-a", ["guitar", "drums"]);
    const effective = resolveEffectiveMixer(track([rootA]), rootA).stems;
    const original: Mix = {
      guitar: { volume: 0.7, muted: true, solo: false },
      drums: { volume: 1.3, muted: true, solo: true },
    };
    const hear = transitionPerformanceShortcut(
      original,
      effective,
      noPerformanceShortcut(),
      "hear-just",
      "guitar",
    );
    const manualSolo = applyManualChannelChange(
      hear.mix,
      effective,
      hear.shortcut,
      "drums",
      { solo: false },
    );

    expect(manualSolo.shortcut.mode).toBe("none");
    expect(manualSolo.mix).toEqual({
      guitar: original.guitar,
      drums: { ...original.drums, solo: false },
    });
  });

  it("restores play-with-band before a manual solo invalidates it", () => {
    const rootA = root("root-a", ["guitar", "drums"]);
    const effective = resolveEffectiveMixer(track([rootA]), rootA).stems;
    const original: Mix = {
      guitar: { volume: 0.7, muted: false, solo: false },
      drums: { volume: 1.3, muted: true, solo: false },
    };
    const play = transitionPerformanceShortcut(
      original,
      effective,
      noPerformanceShortcut(),
      "play-with-band",
      "guitar",
    );
    const manualSolo = applyManualChannelChange(
      play.mix,
      effective,
      play.shortcut,
      "drums",
      { solo: true },
    );

    expect(manualSolo.shortcut.mode).toBe("none");
    expect(manualSolo.mix).toEqual({
      guitar: original.guitar,
      drums: { ...original.drums, solo: true },
    });
  });

  it("keeps an unrelated manual mute compatible with an active shortcut", () => {
    const rootA = root("root-a", ["guitar", "drums"]);
    const effective = resolveEffectiveMixer(track([rootA]), rootA).stems;
    const original = mixForStems({}, effective);
    const play = transitionPerformanceShortcut(
      original,
      effective,
      noPerformanceShortcut(),
      "play-with-band",
      "guitar",
    );
    const unrelatedMute = applyManualChannelChange(
      play.mix,
      effective,
      play.shortcut,
      "drums",
      { muted: true },
    );
    const off = transitionPerformanceShortcut(
      unrelatedMute.mix,
      effective,
      unrelatedMute.shortcut,
      "none",
      "guitar",
    );

    expect(unrelatedMute.shortcut.mode).toBe("play-with-band");
    expect(unrelatedMute.mix.guitar.muted).toBe(true);
    expect(off.mix).toEqual({
      guitar: original.guitar,
      drums: { ...original.drums, muted: true },
    });
  });

  it.each(["play-with-band", "hear-just"] as const)(
    "restores %s before applying a selected-family mute",
    (mode) => {
      const rootA = root("root-a", ["guitar", "drums"]);
      const effective = resolveEffectiveMixer(track([rootA]), rootA).stems;
      const original: Mix = {
        guitar: { volume: 0.8, muted: false, solo: false },
        drums: { volume: 1.2, muted: false, solo: true },
      };
      const active = transitionPerformanceShortcut(
        original,
        effective,
        noPerformanceShortcut(),
        mode,
        "guitar",
      );
      const manualMute = applyManualChannelChange(
        active.mix,
        effective,
        active.shortcut,
        "guitar",
        { muted: true },
      );

      expect(manualMute.shortcut.mode).toBe("none");
      expect(manualMute.mix).toEqual({
        guitar: { ...original.guitar, muted: true },
        drums: original.drums,
      });
    },
  );

  it("keeps volume edits compatible with an active shortcut", () => {
    const rootA = root("root-a", ["guitar", "drums"]);
    const effective = resolveEffectiveMixer(track([rootA]), rootA).stems;
    const original = mixForStems({}, effective);
    const hear = transitionPerformanceShortcut(
      original,
      effective,
      noPerformanceShortcut(),
      "hear-just",
      "guitar",
    );
    const manualVolume = applyManualChannelChange(
      hear.mix,
      effective,
      hear.shortcut,
      "guitar",
      { volume: 1.4 },
    );

    expect(manualVolume.shortcut.mode).toBe("hear-just");
    expect(manualVolume.mix.guitar).toEqual({
      ...hear.mix.guitar,
      volume: 1.4,
    });
  });
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

describe("beat grid mode controls", () => {
  for (const enabled of [false, true]) {
    it(`shows the sticky ${enabled ? "Auto" : "Raw"} mode and current grid status`, () => {
      const project = track([]);
      project.beat_analysis = {
        status: "ready", message: "", error: null,
        beats: [0, 0.5, 1, 1.5], downbeats: [0], time_signature: 4,
        provider: "CPJKU/beat_this", model: "final0",
      };
      vi.stubGlobal("localStorage", {
        getItem: (key: string) => key === correctionPreferenceKey(project.id) ? String(enabled) : null,
        setItem: () => {},
      });
      try {
        const html = renderToStaticMarkup(<Mixer track={project} />);
        expect(html).toContain("Metronome");
        expect(html).toContain(enabled
          ? "Grid: Auto · Preparing"
          : "Grid: Raw · Override");
        expect(html).toContain('aria-label="Beat grid mode"');
        expect(html).toContain("Engine decision");
        expect(html).toContain("Evaluating beat grid…");
        expect(html).toContain("Source analysis");
        expect(html).toContain("BeatThis");
        expect(html).toContain("The Auto / Raw choice is remembered the next time you open this song.");
        expect(html.match(new RegExp(`<button[^>]*aria-pressed="${enabled}"[^>]*>Auto</button>`))).not.toBeNull();
        expect(html.match(new RegExp(`<button[^>]*aria-pressed="${!enabled}"[^>]*>Raw</button>`))).not.toBeNull();
        expect(html).not.toContain("EXPERIMENTAL beat correction");
      } finally {
        vi.unstubAllGlobals();
      }
    });
  }
});


describe("automatic beat preparation controls", () => {
  for (const status of [undefined, "queued", "processing", "error"] as const) {
    it(`shows only relevant compact controls for ${status ?? "legacy"} analysis`, () => {
      const project = track([]);
      if (status) project.beat_analysis = { status, message: "", error: status === "error" ? "Install beat tracking, then Retry." : null };
      const html = renderToStaticMarkup(<Mixer track={project} />);
      expect(html).not.toContain("Analyze beats");
      expect(html.includes('aria-label="Retry beat analysis"')).toBe(status === "error");
      expect(html.includes("Beats queued…")).toBe(status === "queued");
      expect(html.includes("Analyzing beats…")).toBe(status === "processing");
      expect(html).not.toContain("Beat correction");
    });
  }
});

type CapturedEffect = { callback: () => void | (() => void); deps: unknown[] };

function mixerClickHarness() {
  const player = { setClickOptions: vi.fn(), setRate: vi.fn(), setPitch: vi.fn() };
  const harness = {
    player, states: [] as any[], refs: [] as any[],
    stateCursor: 0, refCursor: 0, effects: [] as CapturedEffect[],
  };
  const committed = new Map<string, { deps: unknown[]; cleanup?: () => void }>();
  let tree: any;
  return {
    player,
    render(project: Track, run?: Run) {
      harness.stateCursor = harness.refCursor = 0;
      harness.effects = [];
      hookHarness.current = harness;
      try { tree = Mixer({ track: project, run }); }
      finally { hookHarness.current = null; }
    },
    step(name: string, match: (deps: unknown[]) => boolean, occurrence = 0) {
      const effects = harness.effects.filter(effect => match(effect.deps));
      expect(effects, `${name} effects`).toHaveLength(occurrence + 1);
      const effect = effects[occurrence];
      const previous = committed.get(name);
      if (previous && effect.deps.length === previous.deps.length &&
          effect.deps.every((dep, index) => Object.is(dep, previous.deps[index]))) return;
      previous?.cleanup?.();
      const cleanup = effect.callback();
      committed.set(name, { deps: effect.deps, cleanup: cleanup || undefined });
    },
    sync() {
      this.step("click sync", deps => deps.length === 3 &&
        typeof deps[0] === "string" && typeof deps[1] === "number" && typeof deps[2] === "boolean");
    },
    request(project: Track) {
      this.step("correction request", deps => deps.length === 2 &&
        deps[0] === `${project.id}:${JSON.stringify(project.beat_analysis)}`);
    },
    preference(project: Track) {
      // Preference precedes practice loading; both depend only on the song ID.
      const effects = harness.effects.filter(effect => effect.deps.length === 1 && effect.deps[0] === project.id);
      expect(effects).toHaveLength(2);
      this.step("correction preference", deps => deps === effects[0].deps);
    },
    button(label: string) {
      const buttons: any[] = [];
      const visit = (node: any) => {
        if (Array.isArray(node)) return node.forEach(visit);
        if (!node?.props) return;
        if (node.type === "button" && node.props.children === label) buttons.push(node);
        visit(node.props.children);
      };
      visit(tree);
      expect(buttons).toHaveLength(1);
      return buttons[0].props;
    },
    gridSummary() {
      const summaries: any[] = [];
      const visit = (node: any) => {
        if (Array.isArray(node)) return node.forEach(visit);
        if (!node?.props) return;
        if (node.type === "summary" && node.props["aria-label"]?.startsWith("Beat grid:")) {
          summaries.push(node);
        }
        visit(node.props.children);
      };
      visit(tree);
      expect(summaries).toHaveLength(1);
      return summaries[0].props;
    },
    click(label: string) {
      const button = this.button(label);
      expect(button.disabled).not.toBe(true);
      button.onClick();
    },
    control(match: (node: any) => boolean) {
      const matches: any[] = [];
      const visit = (node: any) => {
        if (Array.isArray(node)) return node.forEach(visit);
        if (!node?.props) return;
        if (match(node)) matches.push(node);
        visit(node.props.children);
      };
      visit(tree);
      expect(matches).toHaveLength(1);
      return matches[0].props;
    },
  };
}

describe("song playback preferences (stepped hooks, no DOM)", () => {
  const key = (id: string) => `riffroom:playback:${id}`;
  const song = (id = "song-a") => ({ ...track([]), id });
  const speed = (h: ReturnType<typeof mixerClickHarness>) =>
    h.control(node => node.type === "select" && node.props.children?.[0]?.type === "option");
  const pitch = (h: ReturnType<typeof mixerClickHarness>) =>
    h.control(node => node.props["aria-label"] === "Pitch");
  const exactPitch = (h: ReturnType<typeof mixerClickHarness>) =>
    h.control(node => node.props["aria-label"] === "Exact pitch in semitones");

  function mount(project: Track, run?: Run) {
    vi.stubGlobal("document", { addEventListener: vi.fn(), removeEventListener: vi.fn() });
    vi.stubGlobal("window", { setInterval: vi.fn(), clearInterval: vi.fn() });
    const h = mixerClickHarness();
    h.render(project, run);
    h.step("engine creation", deps => deps.length === 0);
    return h;
  }

  it("persists each song independently across remounts, original audio, and root takes", () => {
    const storage = memoryStorage();
    vi.stubGlobal("localStorage", storage);
    const rootA = root("root-a", ["guitar"]);
    const rootB = root("root-b", ["vocals"]);
    const a = { ...song(), runs: [rootA, rootB] };
    const h = mixerClickHarness();
    h.render(a, rootA);
    speed(h).onChange({ target: { value: "0.75" } });
    h.render(a, rootA);
    pitch(h).onChange({ target: { value: "-2.3" } });
    expect(JSON.parse(storage.getItem(key(a.id))!)).toEqual({ rate: 0.75, pitch: -2.3 });

    const loadedPreferences: { rate: number; pitch: number }[] = [];
    const load = vi.spyOn(MixerEngine.prototype, "load").mockImplementation(async function (this: MixerEngine) {
      loadedPreferences.push({ rate: this.rate, pitch: this.pitchSemitones });
    });
    for (const run of [rootA, rootB, undefined]) {
      const reopened = mount(a, run);
      expect(speed(reopened).value).toBe(0.75);
      expect(pitch(reopened).value).toBe(-2.3);
      expect(exactPitch(reopened).value).toBe("-2.3");
      // Mix preservation precedes graph loading; both depend on graphKey.
      reopened.step("graph load", deps => deps.length === 1 && typeof deps[0] === "string" &&
        deps[0].includes("/api/tracks/"), 1);
    }
    expect(load).toHaveBeenCalledTimes(3);
    expect(loadedPreferences).toEqual(Array(3).fill({ rate: 0.75, pitch: -2.3 }));
    const b = song("song-b");
    const other = mixerClickHarness();
    other.render(b);
    expect(speed(other).value).toBe(1);
    expect(pitch(other).value).toBe(0);
    pitch(other).onChange({ target: { value: "4.1" } });
    const reopened = mixerClickHarness();
    reopened.render(a, rootB);
    expect(pitch(reopened).value).toBe(-2.3);
    expect(JSON.parse(storage.getItem(key(b.id))!)).toEqual({ rate: 1, pitch: 4.1 });
  });

  it.each([
    null, "{broken", "null", "[]", "42",
    '{"rate":0.8,"pitch":13}', '{"rate":"0.75","pitch":"2.3"}',
    '{"rate":1e999,"pitch":-1e999}',
  ])("uses safe defaults for missing or corrupt preferences: %s", saved => {
    const storage = memoryStorage();
    if (saved !== null) storage.setItem(key("song-a"), saved);
    vi.stubGlobal("localStorage", storage);
    const setRate = vi.spyOn(MixerEngine.prototype, "setRate");
    const setPitch = vi.spyOn(MixerEngine.prototype, "setPitch");
    const h = mount(song());
    expect(speed(h).value).toBe(1);
    expect(exactPitch(h).value).toBe("0.0");
    expect(setRate).toHaveBeenCalledWith(1);
    expect(setPitch).toHaveBeenCalledWith(0);
  });

  it("keeps controls and engine usable when storage reads and writes are blocked", () => {
    vi.stubGlobal("localStorage", {
      getItem: () => { throw new Error("blocked"); },
      setItem: () => { throw new Error("blocked"); },
    });
    const setRate = vi.spyOn(MixerEngine.prototype, "setRate");
    const setPitch = vi.spyOn(MixerEngine.prototype, "setPitch");
    const h = mount(song());
    speed(h).onChange({ target: { value: "1.1" } });
    h.render(song());
    pitch(h).onChange({ target: { value: "0.1" } });
    h.render(song());
    expect(speed(h).value).toBe(1.1);
    expect(exactPitch(h).value).toBe("0.1");
    expect(setRate).toHaveBeenLastCalledWith(1.1);
    expect(setPitch).toHaveBeenLastCalledWith(0.1);
  });

  it("persists exact pitch edits and explicit resets and seeds the next engine with zero", () => {
    const storage = memoryStorage();
    storage.setItem(key("song-a"), JSON.stringify({ rate: 0.5, pitch: 2.3 }));
    vi.stubGlobal("localStorage", storage);
    const setRate = vi.spyOn(MixerEngine.prototype, "setRate");
    const setPitch = vi.spyOn(MixerEngine.prototype, "setPitch");
    const h = mount(song());
    exactPitch(h).onBlur({ target: { value: "3.14" } });
    h.render(song());
    expect(exactPitch(h).value).toBe("3.1");
    expect(JSON.parse(storage.getItem(key("song-a"))!).pitch).toBe(3.1);
    speed(h).onChange({ target: { value: "1" } });
    h.render(song());
    h.control(node => node.props["aria-label"] === "Reset pitch to zero").onClick();
    expect(setRate).toHaveBeenLastCalledWith(1);
    expect(setPitch).toHaveBeenLastCalledWith(0);
    expect(JSON.parse(storage.getItem(key("song-a"))!)).toEqual({ rate: 1, pitch: 0 });
    const reopened = mount(song());
    expect(speed(reopened).value).toBe(1);
    expect(exactPitch(reopened).value).toBe("0.0");
    expect(setRate).toHaveBeenLastCalledWith(1);
    expect(setPitch).toHaveBeenLastCalledWith(0);
  });
});

describe("Mixer beat-grid synchronization (stepped hooks, no DOM)", () => {
  const raw: BeatGrid = {
    beats: [0, 0.25, 0.5, 0.75, 1, 1.5, 2, 2.5, 3, 3.5, 4],
    downbeats: [0, 2, 4], time_signature: 4,
  };
  const corrected: BeatGrid = { ...raw, beats: [0, 0.5, 1, 1.5, 2, 2.5, 3, 3.5, 4] };
  const song = (id = "song-a"): Track => ({
    ...track([]), id,
    beat_analysis: { ...raw, status: "ready", message: "", error: null, created_at: "first" },
  });
  const proposal = (project: Track): BeatCorrection => ({
    status: "applied", source_analysis: project.beat_analysis as BeatAnalysis, grid: corrected,
  });
  function setup(enabled = false) {
    const storage = memoryStorage();
    storage.setItem(correctionPreferenceKey("song-a"), String(enabled));
    vi.stubGlobal("localStorage", storage);
    let resolve!: (response: Response) => void;
    const response = new Promise<Response>(done => { resolve = done; });
    const fetch = vi.fn(() => response);
    vi.stubGlobal("fetch", fetch);
    return { harness: mixerClickHarness(), storage, fetch, resolve };
  }
  async function deliver(
    setupResult: ReturnType<typeof setup>, project: Track, selected: BeatGrid,
  ) {
    setupResult.resolve(Response.json(proposal(project)));
    await vi.waitFor(() => {
      setupResult.harness.render(project);
      setupResult.harness.sync();
      expect(setupResult.harness.player.setClickOptions).toHaveBeenLastCalledWith(selected, 2, false);
      // With Raw selected the sync call is unchanged; the real UI description
      // proves the async request closure has stored its validated proposal.
      const summary = setupResult.harness.gridSummary();
      expect(summary["aria-label"])
        .toBe(selected === corrected ? "Beat grid: Auto · Corrected" : "Beat grid: Raw · Override");
      expect(summary.title).toContain("Correction applied");
    });
  }

  it("keeps Raw on a late response, then propagates explicit Auto/Raw changes", async () => {
    const state = setup();
    const project = song();
    const { harness } = state;
    harness.render(project);
    harness.sync();
    expect(harness.player.setClickOptions).toHaveBeenLastCalledWith(raw, 2, false);
    harness.request(project);
    expect(state.fetch).toHaveBeenCalledWith(`/api/tracks/${project.id}/beats/correction`, expect.anything());
    await deliver(state, project, raw);
    expect(harness.player.setClickOptions).toHaveBeenCalledTimes(1);
    harness.click("Auto");
    harness.render(project);
    harness.sync();
    expect(harness.player.setClickOptions).toHaveBeenLastCalledWith(corrected, 2, false);
    expect(state.storage.getItem(correctionPreferenceKey(project.id))).toBe("true");
    harness.click("Raw");
    harness.render(project);
    harness.sync();
    expect(harness.player.setClickOptions).toHaveBeenLastCalledWith(raw, 2, false);
    expect(state.storage.getItem(correctionPreferenceKey(project.id))).toBe("false");
  });

  it("propagates a late correction from pending silence without another user action", async () => {
    const state = setup(true);
    const project = song();
    state.harness.render(project);
    state.harness.sync();
    expect(state.harness.player.setClickOptions).toHaveBeenLastCalledWith(null, 2, false);
    state.harness.request(project);
    await deliver(state, project, corrected);
    expect(state.harness.player.setClickOptions).toHaveBeenCalledTimes(2);
  });

  it.each([false, true])("does not reuse another song's proposal with identical analysis (second song Auto: %s)", async (auto) => {
    const state = setup(true);
    const first = song();
    state.harness.render(first);
    state.harness.request(first);
    await deliver(state, first, corrected);
    const second = song("song-b");
    if (!auto) state.storage.setItem(correctionPreferenceKey(second.id), "false");
    state.harness.render(second);
    state.harness.sync();
    expect(state.harness.player.setClickOptions).toHaveBeenLastCalledWith(null, 2, false);
    state.harness.preference(second);
    state.harness.render(second);
    state.harness.sync();
    expect(state.harness.player.setClickOptions).toHaveBeenLastCalledWith(auto ? null : raw, 2, false);
    expect(state.harness.button("Auto")["aria-pressed"]).toBe(auto);
    expect(state.harness.button("Raw")["aria-pressed"]).toBe(!auto);
    expect(state.storage.getItem(correctionPreferenceKey(first.id))).toBe("true");
    expect(state.storage.getItem(correctionPreferenceKey(second.id))).toBe(auto ? null : "false");
  });

  it("invalidates a proposal when the same song's analysis snapshot changes", async () => {
    const state = setup(true);
    const project = song();
    state.harness.render(project);
    state.harness.request(project);
    await deliver(state, project, corrected);
    state.harness.render({ ...project, beat_analysis: { ...project.beat_analysis!, created_at: "replacement" } });
    state.harness.sync();
    expect(state.harness.player.setClickOptions).toHaveBeenLastCalledWith(null, 2, false);
  });

  it("ignores equivalent polling grids but propagates beat, accent, and meter changes", () => {
    const { harness } = setup();
    const project = song();
    harness.render(project);
    harness.sync();
    harness.render({ ...project, beat_analysis: structuredClone(project.beat_analysis) });
    harness.sync();
    expect(harness.player.setClickOptions).toHaveBeenCalledTimes(1);
    for (const change of [{ beats: corrected.beats }, { downbeats: [0, 3] }, { time_signature: 3 }]) {
      project.beat_analysis = { ...project.beat_analysis!, ...change };
      harness.render(project);
      harness.sync();
      expect(harness.player.setClickOptions).toHaveBeenLastCalledWith(
        { beats: project.beat_analysis.beats, downbeats: project.beat_analysis.downbeats,
          time_signature: project.beat_analysis.time_signature }, 2, false,
      );
    }
    expect(harness.player.setClickOptions).toHaveBeenCalledTimes(4);
  });
});
