import { describe, expect, it } from "vitest";
import { countInClicks, gridClicksBetween, validBeatGrid } from "./beatGrid";

const grid = {
  beats: [0, 0.5, 1, 1.5, 2, 2.5, 3, 3.5, 4],
  downbeats: [0, 2, 4],
  time_signature: 4,
};

describe("beat-grid click planning", () => {
  it("counts into an exact arbitrary position without moving it", () => {
    expect(countInClicks(grid, 2.25, 1)).toEqual([
      { songTime: 0.5, accent: false },
      { songTime: 1, accent: false },
      { songTime: 1.5, accent: false },
      { songTime: 2, accent: true },
    ]);
  });

  it("extends a valid model grid backward for a sparse intro while preserving phase", () => {
    expect(countInClicks(grid, 0, 1)).toEqual([
      { songTime: -2, accent: true },
      { songTime: -1.5, accent: false },
      { songTime: -1, accent: false },
      { songTime: -0.5, accent: false },
    ]);
  });

  it("puts sparse-intro count-in before a playhead earlier than the first detection", () => {
    const sparseIntro = {
      beats: [8, 8.5, 9, 9.5, 10],
      downbeats: [8, 10],
      time_signature: 4,
    };
    expect(countInClicks(sparseIntro, 0.25, 1)).toEqual([
      { songTime: -1.5, accent: false },
      { songTime: -1, accent: false },
      { songTime: -0.5, accent: false },
      { songTime: 0, accent: true },
    ]);
  });

  it.each([1, 2, 3, 4])(
    "returns exactly %s requested count-in bars",
    (bars) => {
      const clicks = countInClicks(grid, 2.25, bars);
      expect(clicks).toHaveLength(bars * grid.time_signature);
      expect(clicks.at(-1)?.songTime).toBe(2);
      expect(clicks.every((click) => click.songTime < 2.25)).toBe(true);
    },
  );

  it("uses the local grid interval to lead into a point after the final detection", () => {
    expect(countInClicks(grid, 6.25, 1)).toEqual([
      { songTime: 4.5, accent: false },
      { songTime: 5, accent: false },
      { songTime: 5.5, accent: false },
      { songTime: 6, accent: true },
    ]);
  });

  it("hands boundary beats to exactly one adjacent segment", () => {
    expect(
      gridClicksBetween(grid, 0, 2).map((click) => click.songTime),
    ).toEqual([0, 0.5, 1, 1.5]);
    expect(
      gridClicksBetween(grid, 2, 3).map((click) => click.songTime),
    ).toEqual([2, 2.5]);
  });

  it("rejects sparse and invalid grids instead of inventing timing", () => {
    expect(
      validBeatGrid({ beats: [1], downbeats: [1], time_signature: 4 }),
    ).toBe(false);
    expect(
      validBeatGrid({ beats: [1, 0.5], downbeats: [], time_signature: 4 }),
    ).toBe(false);
    expect(countInClicks(null, 3, 2)).toEqual([]);
  });
});

it("does not extrapolate pulses inside an abstained detector gap", () => {
  const irregular = { beats: [0, 0.5, 1, 1.5, 3.01, 3.5, 4, 4.5, 5],
    downbeats: [0, 3.01, 5], time_signature: 4 };
  expect(countInClicks(irregular, 3.01, 1).map(click => click.songTime)).toEqual([0, 0.5, 1, 1.5]);
});
