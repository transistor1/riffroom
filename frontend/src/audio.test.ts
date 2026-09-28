import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { channelGain, MixerEngine, stretchParametersForRate } from "./audio";
import type { MetronomeSettings } from "./types";

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
const oscillators: any[] = [];
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
      gain: {
        value: 0,
        setTargetAtTime: vi.fn(),
        setValueAtTime: vi.fn(),
        linearRampToValueAtTime: vi.fn(),
        exponentialRampToValueAtTime: vi.fn(),
      },
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
  createOscillator() {
    const oscillator = {
      context: this,
      frequency: { value: 0 },
      start: vi.fn(),
      stop: vi.fn(),
      disconnect: vi.fn(),
      onended: null as (() => void) | null,
      gain: null as any,
      connect(gain: any) {
        this.gain = gain;
        return gain;
      },
    };
    oscillators.push(oscillator);
    return oscillator;
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
  oscillators.length = 0;
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
  vi.stubGlobal(
    "AudioContext",
    class extends Context {
      constructor() {
        super();
        Object.assign(this, { audioWorklet: undefined });
      }
    },
  );
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
  player.setLoop({ a: 2, b: 4, enabled: true });
  player.setRate(0.5);
  await player.play();
  clock.currentTime = 5.04;
  expect(player.position()).toBeCloseTo(2.5);
  expect(nodes[0].loop).toBe(true);
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
  expect(nodes.slice(-2).map((node) => node.playbackRate.value)).toEqual([
    0.5, 0.5,
  ]);
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

describe("smart metronome", () => {
  let player: MixerEngine;
  const settings: MetronomeSettings = {
    enabled: true,
    volume: 0.5,
    subdivision: 1,
    accent: true,
    countIn: false,
  };
  const times = () =>
    oscillators.map((node) => node.start.mock.calls[0][0] as number);
  const expectTimes = (expected: number[]) => {
    expect(times()).toHaveLength(expected.length);
    times().forEach((time, index) =>
      expect(time).toBeCloseTo(expected[index], 8),
    );
  };
  // Timer ticks only refill the queue. AudioContext time independently determines it.
  const advanceAudioTo = (target: number) => {
    while (clock.currentTime < target) {
      clock.currentTime = Math.min(target, clock.currentTime + 0.025);
      vi.advanceTimersByTime(25);
    }
  };
  const expectCancelled = (stale: typeof oscillators) => {
    for (const node of stale) {
      expect(node.stop).toHaveBeenLastCalledWith();
      expect(node.disconnect).toHaveBeenCalledOnce();
      expect(node.gain.disconnect).toHaveBeenCalledOnce();
      expect(node.onended).toBeNull();
    }
  };

  beforeEach(async () => {
    vi.useFakeTimers();
    player = new MixerEngine();
    await player.load(stems, new AbortController().signal);
    player.setBeatTimeline({
      version: 1,
      bpm: 120,
      confidence: 0.8,
      beats: Array.from({ length: 20 }, (_, i) => i * 0.5),
    });
    player.setMetronome(settings);
  });
  afterEach(() => {
    player.dispose();
    expect(vi.getTimerCount()).toBe(0);
    vi.useRealTimers();
  });

  it("queues detected beats on the stems' AudioContext clock, independent of timer time", async () => {
    clock.currentTime = 8;
    await player.play();
    expectTimes([8.04]);
    vi.advanceTimersByTime(2000);
    expectTimes([8.04]);
    advanceAudioTo(8.5);
    expectTimes([8.04, 8.54]);
    expect(oscillators.every((node) => node.context === player.context)).toBe(
      true,
    );
    expect(nodes[0].start).toHaveBeenCalledWith(8.04, 0);
  });

  it("doubles real-time beat spacing at half speed", async () => {
    player.setRate(0.5);
    await player.play();
    advanceAudioTo(2);
    expectTimes([0.04, 1.04, 2.04]);
    expect(player.position()).toBeCloseTo(0.98);
  });

  it.each([2, 4] as const)(
    "schedules every intermediate click for subdivision %i",
    async (subdivision) => {
      player.setMetronome({ ...settings, subdivision });
      await player.play();
      advanceAudioTo(0.44);
      expectTimes(
        Array.from(
          { length: subdivision + 1 },
          (_, i) => 0.04 + (i * 0.5) / subdivision,
        ),
      );
    },
  );

  it("accents only every fourth detected beat, never subdivisions", async () => {
    player.setMetronome({ ...settings, subdivision: 4 });
    await player.play();
    advanceAudioTo(2);
    expect(oscillators).toHaveLength(17);
    expect(oscillators.map((node) => node.frequency.value)).toEqual(
      Array.from({ length: 17 }, (_, i) => (i % 16 === 0 ? 1500 : 1000)),
    );
  });

  it("pause cancels queued oscillators and their gains and stops refilling", async () => {
    await player.play();
    const stale = [...oscillators];
    player.pause();
    expectCancelled(stale);
    advanceAudioTo(2);
    expect(oscillators).toHaveLength(stale.length);
    expect(player.position()).toBe(0);
  });

  it.each(["seek", "rate", "loop"] as const)(
    "%s cancels stale clicks and resumes without repeating count-in",
    async (operation) => {
      player.setMetronome({ ...settings, countIn: true });
      await player.play();
      const stale = [...oscillators];
      expect(stale).toHaveLength(4);
      if (operation === "seek") player.seek(3);
      if (operation === "rate") player.setRate(0.5);
      if (operation === "loop") player.setLoop({ a: 2, b: 3, enabled: true });
      await vi.waitFor(() => expect(nodes).toHaveLength(4));
      expectCancelled(stale);
      expect(nodes[2].start.mock.calls[0]).toEqual([
        0.04,
        operation === "seek" ? 3 : operation === "loop" ? 2 : 0,
      ]);
      expect(oscillators).toHaveLength(5);
      advanceAudioTo(0.5);
      const newTimes = times().slice(4);
      expect(newTimes).toHaveLength(operation === "rate" ? 1 : 2);
      if (operation !== "rate") expect(newTimes[1]).toBeCloseTo(0.54);
    },
  );

  it("splits loop windows across both sides without duplicates or out-of-loop beats", async () => {
    player.setMetronome({ ...settings, subdivision: 4 });
    player.setLoop({ a: 1, b: 2, enabled: true });
    player.seek(1.875);
    await player.play();
    advanceAudioTo(1.15);
    expectTimes(Array.from({ length: 11 }, (_, i) => 0.04 + i * 0.125));
    // Beat 4 at loop B is accented, but is excluded in favor of beat 2 at A.
    expect(oscillators.every((node) => node.frequency.value === 1000)).toBe(
      true,
    );
    expect(player.position()).toBeCloseTo(1.985);
  });

  it.each([1, 0.5])(
    "keeps four count-in clicks separate from song scheduling at rate %s",
    async (rate) => {
      // Local spacing differs from the global BPM estimate and earlier beats.
      player.setBeatTimeline({
        version: 1,
        bpm: 120,
        confidence: 0.8,
        beats: [0, 0.5, 1, 2, 3, 3.75, 4.5, 5.25, 6],
      });
      player.setRate(rate);
      player.seek(3);
      player.setMetronome({ ...settings, countIn: true });
      await player.play();
      const interval = 0.75 / rate;
      const startedAt = 0.04 + 4 * interval;
      expectTimes(Array.from({ length: 4 }, (_, i) => 0.04 + i * interval));
      expect(nodes[0].start).toHaveBeenCalledWith(startedAt, 3);
      expect(nodes[1].start).toHaveBeenCalledWith(startedAt, 3);
      advanceAudioTo(startedAt - 0.2);
      expect(player.position()).toBe(3);
      // A nonzero offset exposes negative elapsed-time song clicks during pre-roll.
      expect(oscillators).toHaveLength(4);
      advanceAudioTo(startedAt + interval);
      const songTimes = times().slice(4);
      expect(songTimes).toHaveLength(2);
      expect(songTimes[0]).toBeCloseTo(startedAt);
      expect(songTimes[1]).toBeCloseTo(startedAt + interval);
      expect(songTimes.every((time) => time >= startedAt)).toBe(true);
      expect(player.position()).toBeCloseTo(3.75);
    },
  );

  it("cleans up completed clicks without cancelling them again", async () => {
    await player.play();
    const node = oscillators[0];
    node.onended();
    expect(node.disconnect).toHaveBeenCalledOnce();
    expect(node.gain.disconnect).toHaveBeenCalledOnce();
    player.pause();
    expect(node.stop).toHaveBeenCalledTimes(1);
  });

  it.each([
    [0, 0, 1],
    [0, 0, 0.5],
    [0.2, 0, 1],
    [0.2, 0, 0.5],
    [0.2, 1.35, 1],
    [0.2, 1.35, 0.5],
  ])(
    "phases count-in for first beat %s, offset %s, rate %s",
    async (phase, offset, rate) => {
      const beats = Array.from({ length: 20 }, (_, i) => phase + i * 0.5);
      player.setBeatTimeline({ version: 1, bpm: 120, confidence: 1, beats });
      player.setRate(rate);
      player.seek(offset);
      player.setMetronome({ ...settings, countIn: true });
      await player.play();
      const upcoming = beats.find((beat) => beat >= offset)!;
      const interval = 0.5 / rate;
      const start = 0.04 + (2 - (upcoming - offset)) / rate;
      expectTimes(Array.from({ length: 4 }, (_, i) => 0.04 + i * interval));
      expect(nodes[0].start.mock.calls[0][0]).toBeCloseTo(start);
      expect(nodes[0].start.mock.calls[0][1]).toBe(offset);
      advanceAudioTo(start - 0.01);
      expect(player.position()).toBe(offset);
      advanceAudioTo(0.04 + 5 * interval);
      expectTimes(Array.from({ length: 6 }, (_, i) => 0.04 + i * interval));
      expect(times()[4]).toBeCloseTo(start + (upcoming - offset) / rate);
    },
  );

  it("schedules a louder maximum click independently of stem channel gains", async () => {
    player.setMix({ guitar: { volume: 0, muted: true, solo: false } });
    player.setMaster(1);
    player.setMetronome({ ...settings, volume: 1 });
    await player.play();
    expect(
      oscillators[0].gain.gain.linearRampToValueAtTime,
    ).toHaveBeenCalledWith(0.9, 0.042);
  });

  it("disabling the metronome cancels scheduled clicks", async () => {
    await player.play();
    const stale = [...oscillators];
    player.setMetronome({ ...settings, enabled: false });
    expectCancelled(stale);
    advanceAudioTo(1);
    expect(oscillators).toHaveLength(stale.length);
    expect(player.playing).toBe(true);
  });

  it("preserves immediate stem transport when disabled, even with count-in selected", async () => {
    player.setMetronome({ ...settings, enabled: false, countIn: true });
    player.seek(2);
    await player.play();
    expect(nodes[0].start).toHaveBeenCalledWith(0.04, 2);
    advanceAudioTo(1.04);
    expect(player.position()).toBeCloseTo(3);
    expect(oscillators).toHaveLength(0);
    expect(vi.getTimerCount()).toBe(0);
  });
});
