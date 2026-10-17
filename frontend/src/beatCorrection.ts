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

/** Only detected, ordered song-time beats are usable; never extrapolate an intro. */
export function usableLoopBeats(grid: BeatGrid | null, duration: number): number[] {
  if (!validBeatGrid(grid) || !Number.isFinite(duration) || duration <= 0) return [];
  const beats = grid.beats.filter(beat => beat >= 0 && beat <= duration);
  return beats.length >= 2 ? beats : [];
}

/** Snap within the legal boundary interval, retaining free placement if none fit. */
export function loopBoundaryTime(
  value: number, min: number, max: number, beats: readonly number[],
): number {
  const bounded = Math.max(min, Math.min(Number.isFinite(value) ? value : min, max));
  let nearest = bounded;
  let distance = Infinity;
  for (const beat of beats) {
    if (beat < min || beat > max) continue;
    const delta = Math.abs(beat - bounded);
    // Equal distances choose the earlier beat, consistently across editing paths.
    if (delta < distance) { nearest = beat; distance = delta; }
  }
  return nearest;
}

export const loopSnapPreferenceKey = (trackId: string) =>
  `riffroom:loop-snap:v1:${trackId}`;

export function loadLoopSnapPreference(trackId: string): boolean {
  try { return localStorage.getItem(loopSnapPreferenceKey(trackId)) === "true"; }
  catch { return false; }
}

export function saveLoopSnapPreference(trackId: string, enabled: boolean) {
  try { localStorage.setItem(loopSnapPreferenceKey(trackId), String(enabled)); }
  catch { /* Keep the toggle usable for this session when storage is blocked. */ }
}

/** Step strictly past the current beat (within 10ms); no legal neighbor is a no-op. */
export function nudgeLoopBoundary(
  value: number, direction: -1 | 1, min: number, max: number, beats: readonly number[],
): number {
  // Include the exact tolerance boundary despite floating point subtraction noise.
  const tolerance = 0.01 + 1e-9;
  const candidates = beats.filter(beat => beat >= min && beat <= max &&
    (direction === -1 ? beat < value - tolerance : beat > value + tolerance));
  return (direction === -1 ? candidates.at(-1) : candidates[0]) ?? value;
}
