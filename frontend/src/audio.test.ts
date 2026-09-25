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
