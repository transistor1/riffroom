import { afterEach, describe, expect, it, vi } from "vitest";
import easyLover from "../../backend/tests/fixtures/easy_lover_approved_groove.json";
import easyLoverCorrection from "../../backend/tests/fixtures/easy_lover_correction.json";
import reelin from "../../backend/tests/fixtures/reelin_original_grid.json";
import {
  correctionPreferenceKey, loadCorrectionPreference, saveCorrectionPreference,
  selectedClickGrid, validateCorrection, type BeatCorrection,
} from "./beatCorrection";
import { countInClicks, gridClicksBetween } from "./beatGrid";
import type { BeatAnalysis } from "./types";

afterEach(() => vi.unstubAllGlobals());

describe("experimental per-song correction", () => {
  it("defaults off, remembers explicit choice per song across takes, and reverses", () => {
    const values = new Map<string, string>();
    vi.stubGlobal("localStorage", {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => values.set(key, value),
    });
    expect(loadCorrectionPreference("easy")).toBe(false);
    saveCorrectionPreference("easy", true);
    expect(values.get(correctionPreferenceKey("easy"))).toBe("true");
    expect(loadCorrectionPreference("easy")).toBe(true);
    expect(loadCorrectionPreference("reelin")).toBe(false);
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
});
