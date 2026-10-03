import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { channelGain, MixerEngine, stretchParametersForRate } from "./audio";

const soundTouchMock = vi.hoisted(() => {
  const nodes: any[] = [];
  const register = vi.fn(
    async (context: any, url: string) =>
      await context.audioWorklet.addModule(url),
  );
  class Node {
    static register = register;
    playbackRate = { value: 1 };
    pitchSemitones = { value: 0 };
    setStretchParameters = vi.fn();
    disconnect = vi.fn();
    constructor(public options: any) {
      nodes.push(this);
    }
    connect(node: any) {
      return node;
    }
  }
  return { Node, nodes, register, imported: vi.fn() };
});

vi.mock("@soundtouchjs/audio-worklet", () => {
  soundTouchMock.imported();
  return { SoundTouchNode: soundTouchMock.Node };
});
vi.mock("@soundtouchjs/audio-worklet/processor?url", () => ({
  default: "/assets/soundtouch-processor.js",
}));

const nodes: any[] = [];
// Capture module evaluation before any test can trigger a dynamic import.
const eagerlyImportedSoundTouch = soundTouchMock.imported.mock.calls.length > 0;
let clock: any;
class Context {
  currentTime = 0;
  destination = {};
  audioWorklet = { addModule: vi.fn(async () => {}) };
  resume = vi.fn(async () => {});
  close = vi.fn(async () => {});
  decodeAudioData = vi.fn(async () => ({ duration: 10 }));
  constructor() {
    clock = this;
  }
  createGain() {
    return {
      gain: { value: 0, setTargetAtTime: vi.fn() },
      connect() {
        return this;
      },
      disconnect: vi.fn(),
    };
  }
  createDynamicsCompressor() {
    return {
      threshold: {},
      knee: {},
      ratio: {},
      attack: {},
      release: {},
      connect: vi.fn(),
      disconnect: vi.fn(),
    };
  }
  createBufferSource() {
    const source = {
      playbackRate: { value: 1 },
      start: vi.fn(),
      stop: vi.fn(),
      disconnect: vi.fn(),
      connect(node: any) {
        return node;
      },
      loop: false,
      loopStart: 0,
      loopEnd: 0,
    };
    nodes.push(source);
    return source;
  }
}

const mix = {
  guitar: { volume: 1.5, muted: false, solo: false },
  drums: { volume: 0.7, muted: false, solo: false },
};
const stems = Object.keys(mix).map((name) => ({
  name,
  file: `${name}.wav`,
  url: `/${name}`,
  peaks: [],
}));

beforeEach(() => {
  nodes.length = 0;
  soundTouchMock.nodes.length = 0;
  soundTouchMock.register.mockClear();
  vi.stubGlobal("AudioContext", Context);
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok: true,
      arrayBuffer: async () => new ArrayBuffer(0),
    })),
  );
});
afterEach(() => vi.unstubAllGlobals());

it("imports audio helpers without evaluating the SoundTouch runtime", () => {
  expect(eagerlyImportedSoundTouch).toBe(false);
});

it("loads stems without AudioWorklet and explains the secure origin requirement on playback", async () => {
  vi.stubGlobal("AudioWorkletNode", undefined);
  vi.stubGlobal("AudioContext", class extends Context {
    constructor() {
      super();
      Object.assign(this, { audioWorklet: undefined });
    }
  });
  const importsBefore = soundTouchMock.imported.mock.calls.length;
  const player = new MixerEngine();
  await player.load(stems, new AbortController().signal);
  expect(clock.decodeAudioData).toHaveBeenCalledTimes(stems.length);
  expect(player.duration).toBe(10);
  expect(soundTouchMock.register).not.toHaveBeenCalled();
  expect(soundTouchMock.nodes).toHaveLength(0);
  await expect(player.play()).rejects.toThrow("localhost or HTTPS");
  expect(soundTouchMock.imported).toHaveBeenCalledTimes(importsBefore);
  expect(player.playing).toBe(false);
  expect(nodes).toHaveLength(0);
  player.dispose();
});

describe("mix routing", () => {
  it("respects volume, simultaneous solos and mute precedence", () => {
    expect(channelGain("guitar", mix)).toBe(1.5);
    const solo = { ...mix, drums: { ...mix.drums, solo: true } };
    expect(channelGain("guitar", solo)).toBe(0);
    expect(channelGain("drums", solo)).toBe(0.7);
    expect(
      channelGain("drums", { ...solo, drums: { ...solo.drums, muted: true } }),
    ).toBe(0);
    expect(
      channelGain("guitar", { ...solo, guitar: { ...mix.guitar, solo: true } }),
    ).toBe(1.5);
  });
});

describe("SoundTouch stretch profiles", () => {
  it("uses SoundTouch auto windows only around half speed", () => {
    expect(stretchParametersForRate(0.5)).toEqual({
      sequenceMs: 0,
      seekWindowMs: 0,
      overlapMs: 12,
      quickSeek: false,
    });
    expect(stretchParametersForRate(0.55)).toEqual(
      stretchParametersForRate(0.5),
    );
  });

  it("preserves the existing profile above half speed", () => {
    for (const rate of [0.56, 0.75, 0.9, 1, 1.1, 1.25]) {
      expect(stretchParametersForRate(rate)).toEqual({
        sequenceMs: 80,
        seekWindowMs: 20,
        overlapMs: 12,
        quickSeek: false,
      });
    }
  });
});

it("starts all stems on the same clock and keeps a seek in sync", async () => {
  const player = new MixerEngine();
  player.setMix(mix);
  await player.load(stems, new AbortController().signal);
  await player.play();
  expect(nodes[0].start.mock.calls[0]).toEqual(nodes[1].start.mock.calls[0]);
  clock.currentTime = 2.04;
  expect(player.position()).toBeCloseTo(2);
  player.seek(5);
  await vi.waitFor(() => expect(nodes).toHaveLength(4));
  expect(nodes[0].stop).toHaveBeenCalled();
  expect(nodes[2].start.mock.calls[0][1]).toBe(5);
  expect(nodes[2].start.mock.calls[0]).toEqual(nodes[3].start.mock.calls[0]);
  player.dispose();
});

it("loops and accounts for speed on the shared timeline", async () => {
  const player = new MixerEngine();
  await player.load(stems, new AbortController().signal);
  player.setLoopPlan(true, [{ id: "one", name: "One", a: 2, b: 4, enabled: true }]);
  player.setRate(0.5);
  await player.play();
  clock.currentTime = 3.9;
  (player as any).schedule();
  clock.currentTime = 5.04;
  expect(player.position()).toBeCloseTo(2.5);
  expect(nodes[2].start.mock.calls[0]).toEqual([4.04, 2]);
  expect(nodes[0].playbackRate.value).toBe(0.5);
  player.dispose();
});

it("keeps tempo and requested pitch independent", async () => {
  const player = new MixerEngine();
  await player.load(stems, new AbortController().signal);
  expect(soundTouchMock.register).not.toHaveBeenCalled();
  expect(soundTouchMock.nodes).toHaveLength(0);
  await player.play();
  expect(soundTouchMock.register).toHaveBeenCalledWith(
    clock,
    "/assets/soundtouch-processor.js",
  );
  expect(soundTouchMock.nodes).toHaveLength(1);
  expect(soundTouchMock.nodes[0].options).toEqual({
    context: clock,
    outputChannelCount: 2,
  });
  expect(soundTouchMock.nodes[0].setStretchParameters).toHaveBeenCalledWith({
    sequenceMs: 80,
    seekWindowMs: 20,
    overlapMs: 12,
    quickSeek: false,
  });
  player.setPitch(2);
  expect(soundTouchMock.nodes[0].playbackRate.value).toBe(1);
  expect(soundTouchMock.nodes[0].pitchSemitones.value).toBe(2);
  player.setRate(0.5);
  await vi.waitFor(() => expect(nodes).toHaveLength(4));
  await player.play();
  expect(nodes.slice(-2).map((node) => node.playbackRate.value)).toEqual([0.5, 0.5]);
  const processor = soundTouchMock.nodes.at(-1);
  expect(processor.setStretchParameters).toHaveBeenCalledWith({
    sequenceMs: 0,
    seekWindowMs: 0,
    overlapMs: 12,
    quickSeek: false,
  });
  expect(processor.playbackRate.value).toBe(0.5);
  expect(processor.pitchSemitones.value).toBe(2);
  player.dispose();
});

it("cannot restart after pause while the browser is resuming its audio context", async () => {
  const player = new MixerEngine();
  await player.load(stems, new AbortController().signal);
  let resume!: () => void;
  clock.resume = () =>
    new Promise<void>((resolve) => {
      resume = resolve;
    });
  const play = player.play();
  player.pause();
  resume();
  await play;
  expect(player.playing).toBe(false);
  expect(nodes).toHaveLength(0);
  player.dispose();
});

const regions = [
  { id: "late", name: "Late", a: 6, b: 6.5, enabled: true },
  { id: "off", name: "Off", a: 4, b: 5, enabled: false },
  { id: "early", name: "Early", a: 2, b: 2.5, enabled: true },
];
it("schedules selected regions in order and wraps with all stems synchronized", async () => {
  const player = new MixerEngine();
  await player.load(stems, new AbortController().signal);
  player.setLoopPlan(true, regions);
  player.setRate(0.5);
  await player.play();
  expect(nodes[0].start.mock.calls[0]).toEqual([0.04, 2]);
  expect(nodes[2].start.mock.calls[0]).toEqual([1.04, 6]);
  expect(nodes[0].stop.mock.calls[0][0]).toBe(1.04);
  expect(nodes[2].start.mock.calls).toEqual(nodes[3].start.mock.calls);
  clock.currentTime = 1.54;
  expect(player.position()).toBeCloseTo(6.25);
  (player as any).schedule();
  expect(nodes[4].start.mock.calls[0]).toEqual([2.04, 2]);
  clock.currentTime = 2.14;
  expect(player.position()).toBeCloseTo(2.05);
  player.dispose();
});
it("normalizes outside seeks, retains inside offsets and pause/resume position", async () => {
  const player = new MixerEngine();
  await player.load(stems, new AbortController().signal);
  player.setLoopPlan(true, regions);
  player.seek(4);
  await player.play();
  expect(nodes[0].start.mock.calls[0][1]).toBe(6);
  clock.currentTime = 0.24;
  player.pause();
  expect(player.position()).toBeCloseTo(6.2);
  const count = nodes.length;
  await player.play();
  expect(nodes[count].start.mock.calls[0][1]).toBeCloseTo(6.2);
  player.pause();
  player.seek(9);
  await player.play();
  expect(player.position()).toBe(2);
  player.pause();
  player.seek(2.125);
  await player.play();
  expect(player.position()).toBe(2.125);
  player.dispose();
});
it("cancels queued sources on edits and restores continuous playback when disabled", async () => {
  const player = new MixerEngine();
  await player.load(stems, new AbortController().signal);
  player.setLoopPlan(true, regions);
  await player.play();
  const stale = [...nodes];
  player.setLoopPlan(true, [regions[0]]);
  await vi.waitFor(() => expect(nodes.length).toBeGreaterThan(stale.length));
  stale.forEach(node => expect(node.stop).toHaveBeenCalledTimes(2));
  expect(player.position()).toBe(6);
  player.setLoopPlan(false, regions);
  await vi.waitFor(() => expect(player.playing).toBe(true));
  clock.currentTime = 1.04;
  expect(player.position()).toBeCloseTo(7);
  player.dispose();
});
it("plays normally when no loops are selected and supports overlapping regions", async () => {
  const player = new MixerEngine();
  await player.load(stems, new AbortController().signal);
  player.setLoopPlan(true, regions.map(loop => ({ ...loop, enabled: false })));
  await player.play();
  clock.currentTime = 1.04;
  expect(player.position()).toBeCloseTo(1);
  player.pause();
  player.setLoopPlan(true, [regions[2], { ...regions[0], a: 2.25, b: 3 }]);
  player.seek(2.4);
  await player.play();
  expect(player.position()).toBe(2.4);
  clock.currentTime = 1.28;
  expect(player.position()).toBeCloseTo(2.35);
  player.dispose();
});

import { parseTime, preciseTime } from "./types";
it.each([0.5, 1, 1.25])("resynchronizes after a long scheduler delay at speed %s", async rate => {
  const player = new MixerEngine();
  await player.load(stems, new AbortController().signal);
  // Overlap means the correct route segment cannot be inferred from position alone.
  player.setLoopPlan(true, [regions[2], { ...regions[0], a: 2.25, b: 3 }]);
  player.setRate(rate);
  player.seek(2.4);
  await player.play();
  const count = nodes.length;
  clock.currentTime = 0.04 + 1000.35 / rate;
  const expected = player.position();
  expect(expected).toBeCloseTo(2.5);
  (player as any).schedule();
  expect(nodes[count].start.mock.calls[0][0]).toBe(clock.currentTime);
  expect(nodes[count].start.mock.calls[0][1]).toBeCloseTo(expected);
  expect(nodes[count].stop.mock.calls[0][0]).toBeCloseTo(clock.currentTime + 0.5 / rate);
  expect(player.position()).toBeCloseTo(expected);
  for (let i = count; i < nodes.length; i += stems.length) {
    expect(nodes[i].start.mock.calls[0][0]).toBeGreaterThanOrEqual(clock.currentTime);
    expect(nodes[i].start.mock.calls).toEqual(nodes[i + 1].start.mock.calls);
  }
  player.dispose();
});

it("bounds source creation for 50ms loops after hours without a scheduler tick", async () => {
  const player = new MixerEngine();
  await player.load(stems, new AbortController().signal);
  player.setLoopPlan(true, [{ ...regions[2], a: 0, b: 0.05 }]);
  player.setRate(1.25);
  await player.play();
  expect(nodes.length).toBeLessThanOrEqual(51 * stems.length);
  const count = nodes.length;
  clock.currentTime = 7200.063;
  const expected = player.position();
  (player as any).schedule();
  expect(nodes.length - count).toBeLessThanOrEqual(51 * stems.length);
  expect(nodes[count].start.mock.calls[0][0]).toBe(clock.currentTime);
  expect(nodes[count].start.mock.calls[0][1]).toBeCloseTo(expected);
  player.dispose();
});

it("formats and parses precise boundaries without whole-second rounding", () => {
  expect(preciseTime(62.125)).toBe("1:02.125");
  expect(preciseTime(59.9999)).toBe("1:00.000");
  expect(parseTime("1:02.125")).toBe(62.125);
  expect(parseTime(" 2.125 ")).toBe(2.125);
  for (const invalid of ["", "NaN", "Infinity", "1:60", "-1", "1:2:3"]) expect(parseTime(invalid)).toBeNull();
});
