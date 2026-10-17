import { afterEach, describe, expect, it, vi } from "vitest";
import easyLover from "../../backend/tests/fixtures/easy_lover_approved_groove.json";
import easyLoverCorrection from "../../backend/tests/fixtures/easy_lover_correction.json";
import reelin from "../../backend/tests/fixtures/reelin_original_grid.json";
import comfortablyNumb from "../../backend/tests/fixtures/comfortably_numb_duplicate_grid.json";
import {
  correctionPreferenceKey, loadCorrectionPreference, saveCorrectionPreference,
  selectedClickGrid, validateCorrection, usableLoopBeats, loopBoundaryTime, nudgeLoopBoundary,
  loopSnapPreferenceKey, loadLoopSnapPreference, saveLoopSnapPreference, type BeatCorrection,
} from "./beatCorrection";
import { countInClicks, gridClicksBetween } from "./beatGrid";
import type { BeatAnalysis, BeatGrid } from "./types";

afterEach(() => vi.unstubAllGlobals());

describe("per-song beat correction mode", () => {
  it("defaults to Auto, remembers explicit Raw/Auto choices per song across takes, and reverses", () => {
    const values = new Map<string, string>();
    vi.stubGlobal("localStorage", {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => values.set(key, value),
    });
    expect(loadCorrectionPreference("easy")).toBe(true);
    saveCorrectionPreference("easy", true);
    expect(values.get(correctionPreferenceKey("easy"))).toBe("true");
    expect(loadCorrectionPreference("easy")).toBe(true);
    expect(loadCorrectionPreference("reelin")).toBe(true);
    saveCorrectionPreference("easy", false);
    expect(loadCorrectionPreference("easy")).toBe(false);
  });

  it("switches actual Easy Lover proposal without mutating source or silently falling back", () => {
    const source = easyLover.source_analysis as BeatAnalysis;
    const before = JSON.stringify(source);
    const result = easyLoverCorrection as BeatCorrection;
    validateCorrection(result, source);
    expect(selectedClickGrid(easyLover.source_analysis, true, result)?.beats).toHaveLength(646);
    expect(selectedClickGrid(easyLover.source_analysis, false, result)).toBe(easyLover.source_analysis);
    expect(selectedClickGrid(easyLover.source_analysis, true, null)).toBeNull();
    expect(JSON.stringify(source)).toBe(before);
    const grid = result.grid;
    // The retained beat at source index 38 is corrected index 28. Count-in
    // uses corrected pulse indices; source indices must not shift its phase.
    const position = grid.beats[28];
    const clicks = countInClicks(grid, position, 1);
    expect(clicks.map(click => click.songTime)).toEqual(grid.beats.slice(24, 28));
    expect(clicks.map(click => click.accent)).toEqual([true, false, false, false]);
    expect(gridClicksBetween(grid, position, grid.beats[29])).toEqual([
      { songTime: position, accent: true },
    ]);
  });

  it("keeps Reelin unchanged on abstention and rejects stale/invalid/changed downbeats", () => {
    const source = reelin.source_analysis as BeatAnalysis;
    const result: BeatCorrection = { status: "no_confident_repair", source_analysis: source,
      grid: reelin.source_analysis };
    expect(validateCorrection(result, source)).toBe(result);
    expect(selectedClickGrid(reelin.source_analysis, true, result)?.beats).toEqual(source.beats);
    expect(() => validateCorrection(result, { ...source, created_at: "new" })).toThrow("stale");
    expect(() => validateCorrection({ ...result, grid: { ...result.grid, beats: [1, 0] } }, source)).toThrow();
    expect(() => validateCorrection({ ...result, grid: { ...result.grid, downbeats: [] } }, source)).toThrow();
    expect(() => validateCorrection({ ...result, grid: { ...result.grid, beats: [1, 2] } }, source)).toThrow();
  });

  it("accepts a removal-only duplicate proposal and preserves Raw and downbeat metadata", () => {
    const source = comfortablyNumb.source_analysis as BeatAnalysis & BeatGrid;
    const before = JSON.stringify(source);
    const removed = new Set(comfortablyNumb.expected_removed_source_indices);
    const grid = { ...source, beats: source.beats.filter((_, index) => !removed.has(index)) };
    const result: BeatCorrection = { status: "applied", source_analysis: source, grid };
    expect(validateCorrection(result, source)).toBe(result);
    expect(selectedClickGrid(source, false, result)).toBe(source);
    expect(selectedClickGrid(source, true, result)).toBe(grid);
    const clicks = gridClicksBetween(grid, 64.515, 124.459);
    expect(clicks).toHaveLength(63);
    expect(clicks.some(click => click.songTime === 65.22)).toBe(false);
    expect(clicks.some(click => click.songTime === 65.3)).toBe(true);
    expect(clicks.find(click => click.songTime === 71.92)?.accent).toBe(true);
    expect(grid.downbeats).toEqual(source.downbeats);
    expect(JSON.stringify(source)).toBe(before);
  });
});


describe("practice loop beat snapping", () => {
  const grid: BeatGrid = { beats: [0, 0.5, 1, 1.5, 2, 2.5, 3, 3.5, 4],
    downbeats: [0, 2, 4], time_signature: 4 };

  it("snaps to nearest beats in 4/4, resolves ties earlier, and leaves free edits exact", () => {
    const beats = usableLoopBeats(grid, 4);
    expect(loopBoundaryTime(1.29, 0, 4, beats)).toBe(1.5);
    expect(loopBoundaryTime(1.25, 0, 4, beats)).toBe(1);
    expect(loopBoundaryTime(1.29, 0, 4, [])).toBe(1.29);
    expect(loopBoundaryTime(1.29, 0, 4, usableLoopBeats({ ...grid, time_signature: 3 }, 4))).toBe(1.5);
  });

  it("uses detected sparse intro timestamps without extrapolating or changing the source", () => {
    const sparse = { ...grid, beats: [12.2, 13.7, 14.2, 14.7] };
    const before = JSON.stringify(sparse);
    expect(loopBoundaryTime(2, 0, 30, usableLoopBeats(sparse, 30))).toBe(12.2);
    // No beat fits before the opposite boundary: preserve free placement.
    expect(loopBoundaryTime(2, 0, 5, usableLoopBeats(sparse, 30))).toBe(2);
    expect(JSON.stringify(sparse)).toBe(before);
  });

  it("keeps bounds and a minimum loop length even when the nearest beat would collapse it", () => {
    const beats = usableLoopBeats({ ...grid, beats: [-1, 0, 1, 2, 3, 4, 8] }, 4);
    expect(beats).toEqual([0, 1, 2, 3, 4]);
    expect(loopBoundaryTime(2, 0, 1.95, beats)).toBe(1);
    expect(loopBoundaryTime(2, 2.05, 4, beats)).toBe(3);
    expect(loopBoundaryTime(999, 0, 4, beats)).toBe(4);
    expect(loopBoundaryTime(-1, 0, 4, beats)).toBe(0);
    expect(loopBoundaryTime(0, 0.01, 0.06, beats)).toBe(0.01);
  });

  it("falls back on missing, invalid, or insufficient in-track beats", () => {
    for (const candidate of [null, { ...grid, beats: [] }, { ...grid, beats: [1] },
      { ...grid, beats: [1, NaN] }, { ...grid, beats: [2, 1] },
      { ...grid, beats: [-2, -1, 1, 8] }]) {
      const beats = usableLoopBeats(candidate, 4);
      expect(beats).toEqual([]);
      expect(loopBoundaryTime(1.234, 0, 4, beats)).toBe(1.234);
    }
  });
});


describe("loop snap preference and directional nudges", () => {
  it("defaults off for absent/corrupt storage and persists strictly per song", () => {
    const values = new Map<string, string>();
    vi.stubGlobal("localStorage", {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => values.set(key, value),
    });
    expect(loadLoopSnapPreference("a")).toBe(false);
    for (const corrupt of ["", "TRUE", "1", "{}", "null", "broken"]) {
      values.set(loopSnapPreferenceKey("a"), corrupt);
      expect(loadLoopSnapPreference("a")).toBe(false);
    }
    saveLoopSnapPreference("a", true);
    expect(loadLoopSnapPreference("a")).toBe(true);
    expect(loadLoopSnapPreference("b")).toBe(false);
    saveLoopSnapPreference("a", false);
    expect(loadLoopSnapPreference("a")).toBe(false);
    vi.stubGlobal("localStorage", {
      getItem: () => { throw new Error("blocked"); },
      setItem: () => { throw new Error("blocked"); },
    });
    expect(loadLoopSnapPreference("a")).toBe(false);
    expect(() => saveLoopSnapPreference("a", true)).not.toThrow();
  });

  it.each([0.99, 0.991, 1, 1.009, 1.01])("treats %s as on the beat within 10ms", value => {
    expect(nudgeLoopBoundary(value, -1, 0, 2, [0, 0.5, 1, 1.5, 2])).toBe(0.5);
    expect(nudgeLoopBoundary(value, 1, 0, 2, [0, 0.5, 1, 1.5, 2])).toBe(1.5);
  });

  it("moves directionally between beats and stops at loop/track limits without fallback steps", () => {
    const beats = [0, 0.5, 1, 1.5, 2];
    expect(nudgeLoopBoundary(1.02, -1, 0, 2, beats)).toBe(1);
    expect(nudgeLoopBoundary(0.98, 1, 0, 2, beats)).toBe(1);
    expect(nudgeLoopBoundary(1.25, -1, 0, 2, beats)).toBe(1);
    expect(nudgeLoopBoundary(1.25, 1, 0, 2, beats)).toBe(1.5);
    expect(nudgeLoopBoundary(1, 1, 0, 1.45, beats)).toBe(1);
    expect(nudgeLoopBoundary(1, -1, 0.55, 2, beats)).toBe(1);
    expect(nudgeLoopBoundary(0, -1, 0, 2, beats)).toBe(0);
    expect(nudgeLoopBoundary(2, 1, 0, 2, beats)).toBe(2);
    expect(nudgeLoopBoundary(1.234, 1, 0, 2, [])).toBe(1.234);
    expect(nudgeLoopBoundary(1.234, -1, 0, 2, [])).toBe(1.234);
    expect(nudgeLoopBoundary(2, -1, 0, 30, [12, 13])).toBe(2);
    expect(nudgeLoopBoundary(2, 1, 0, 30, [12, 13])).toBe(12);
  });
});
