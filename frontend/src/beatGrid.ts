import type { BeatGrid } from "./types";

export type GridClick = { songTime: number; accent: boolean };

const close = (left: number, right: number) => Math.abs(left - right) <= 0.04;

function median(values: number[]): number | null {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2
    ? sorted[middle]
    : (sorted[middle - 1] + sorted[middle]) / 2;
}

export function validBeatGrid(grid?: BeatGrid | null): grid is BeatGrid {
  return (
    !!grid &&
    grid.beats.length >= 2 &&
    grid.time_signature > 0 &&
    grid.beats.every(Number.isFinite) &&
    grid.beats.every(
      (beat, index) => index === 0 || beat > grid.beats[index - 1],
    )
  );
}

export function gridClicksBetween(
  grid: BeatGrid | null,
  start: number,
  end: number,
): GridClick[] {
  if (!validBeatGrid(grid) || end <= start) return [];
  return grid.beats
    .filter((beat) => beat >= start - 1e-7 && beat < end - 1e-7)
    .map((songTime) => ({
      songTime,
      accent: grid.downbeats.some((downbeat) => close(songTime, downbeat)),
    }));
}

/** Build grid-aligned clicks immediately before an exact, unmodified start point. */
export function countInClicks(
  grid: BeatGrid | null,
  position: number,
  bars: number,
): GridClick[] {
  if (!validBeatGrid(grid) || bars < 1) return [];
  const count = Math.floor(bars) * grid.time_signature;
  const insertion = grid.beats.findIndex((beat) => beat >= position);
  const center = insertion < 0 ? grid.beats.length - 1 : insertion;
  const intervalStart = Math.max(0, center - 4);
  const intervalEnd = Math.min(grid.beats.length - 1, center + 4);
  const intervals = grid.beats
    .slice(intervalStart + 1, intervalEnd + 1)
    .map((beat, index) => beat - grid.beats[intervalStart + index]);
  const interval = median(
    intervals.filter((value) => value > 0.12 && value < 3),
  );
  if (!interval) return [];

  const times = grid.beats.filter((beat) => beat < position - 1e-7);
  let cursor = times.at(-1) ?? grid.beats[0];
  if (!times.length) {
    // A detector may omit a quiet intro. Extend its phase backward until the
    // synthetic grid is actually before the requested, unchanged playhead.
    while (cursor >= position - 1e-7) cursor -= interval;
    times.push(cursor);
  } else {
    while (cursor + interval < position - 1e-7) {
      cursor += interval;
      times.push(cursor);
    }
  }
  cursor = times[0] ?? grid.beats[0];
  while (times.length < count) {
    cursor -= interval;
    times.unshift(cursor);
  }
  const selected = times.slice(-count);
  const knownDownbeatIndex = grid.beats.findIndex((beat) =>
    grid.downbeats.some((downbeat) => close(beat, downbeat)),
  );
  const downbeatIndex = knownDownbeatIndex >= 0 ? knownDownbeatIndex : 0;
  return selected.map((songTime) => {
    const exactIndex = grid.beats.findIndex((beat) => close(beat, songTime));
    let anchorIndex = 0;
    for (let index = 1; index < grid.beats.length; index++) {
      if (grid.beats[index] > songTime) break;
      anchorIndex = index;
    }
    const beatIndex =
      exactIndex >= 0
        ? exactIndex
        : anchorIndex +
          Math.round((songTime - grid.beats[anchorIndex]) / interval);
    return {
      songTime,
      accent:
        (((beatIndex - downbeatIndex) % grid.time_signature) +
          grid.time_signature) %
          grid.time_signature ===
        0,
    };
  });
}
