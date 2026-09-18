import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { channelGain, MixerEngine } from "./audio";

const nodes: any[] = [];
let clock: any;
class Context {
  currentTime = 0;
  destination = {};
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

it("starts all stems on the same clock and keeps a seek in sync", async () => {
  const player = new MixerEngine();
  player.setMix(mix);
  await player.load(stems, new AbortController().signal);
  await player.play();
  expect(nodes[0].start.mock.calls[0]).toEqual(nodes[1].start.mock.calls[0]);
  clock.currentTime = 2.04;
  expect(player.position()).toBeCloseTo(2);
  player.seek(5);
  await Promise.resolve();
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
