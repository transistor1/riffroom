import { validBeatGrid } from "./beatGrid";
import type { BeatAnalysis, BeatGrid } from "./types";

export type BeatCorrection = {
  status: "applied" | "no_confident_repair";
  source_analysis: BeatAnalysis;
  grid: BeatGrid;
};

export const correctionPreferenceKey = (trackId: string) =>
  `riffroom:experimental-beat-correction:v1:${trackId}`;

export function loadCorrectionPreference(trackId: string): boolean {
  try {
    const stored = localStorage.getItem(correctionPreferenceKey(trackId));
    return stored === null ? true : stored !== "false";
  }
  catch { return true; }
}

export function saveCorrectionPreference(trackId: string, enabled: boolean) {
  try { localStorage.setItem(correctionPreferenceKey(trackId), String(enabled)); }
  catch { /* Session-only operation is still possible without browser storage. */ }
}

/** Bind a proposal to the exact source snapshot; fail closed on stale/invalid data. */
export function validateCorrection(result: BeatCorrection, source: BeatAnalysis): BeatCorrection {
  if (!result || !["applied", "no_confident_repair"].includes(result.status) ||
      JSON.stringify(result.source_analysis) !== JSON.stringify(source) ||
      !validBeatGrid(result.grid) ||
      result.grid.time_signature !== source.time_signature ||
      JSON.stringify(result.grid.downbeats) !== JSON.stringify(source.downbeats) ||
      (result.status === "no_confident_repair" &&
        JSON.stringify(result.grid.beats) !== JSON.stringify(source.beats))) {
    throw new Error("Experimental beat correction failed: invalid or stale proposal.");
  }
  return result;
}

export function selectedClickGrid(
  raw: BeatGrid | null, enabled: boolean, correction: BeatCorrection | null,
): BeatGrid | null {
  // Pending/failed opt-in is explicit silence, never an unnoticed raw-grid fallback.
  return enabled ? correction?.grid ?? null : raw;
}
