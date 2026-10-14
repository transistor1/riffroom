import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import easyLover from "../../backend/tests/fixtures/easy_lover_approved_groove.json";
import easyLoverCorrection from "../../backend/tests/fixtures/easy_lover_correction.json";
import { countInClicks, gridClicksBetween } from "./beatGrid";
import { selectedClickGrid, type BeatCorrection } from "./beatCorrection";
import {
  channelGain,
  clickGain,
  clickInputFrequency,
  DEFAULT_CLICK_VOLUME,
  MixerEngine,
  reassertPlaybackSession,
  stretchParametersForRate,
} from "./audio";

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
    connect = vi.fn((node: any) => node);
    constructor(public options: any) {
      nodes.push(this);
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
const clickNodes: any[] = [];
const gainNodes: any[] = [];
const limiterNodes: any[] = [];
// Capture module evaluation before any test can trigger a dynamic import.
const eagerlyImportedSoundTouch = soundTouchMock.imported.mock.calls.length > 0;
let clock: any;
let decodedDuration = 10;
class Context {
  state = "suspended";
  currentTime = 0;
  destination = {};
  audioWorklet = { addModule: vi.fn(async () => {}) };
  resume = vi.fn(async () => {});
  suspend = vi.fn(async () => { this.state = "suspended"; });
  close = vi.fn(async () => {});
  decodeAudioData = vi.fn(async () => ({ duration: decodedDuration }));
  constructor() {
    clock = this;
  }
  createGain() {
    const node = {
      gain: {
        value: 0,
        setTargetAtTime: vi.fn(),
        setValueAtTime: vi.fn(),
        exponentialRampToValueAtTime: vi.fn(),
      },
      connect: vi.fn((target: any) => target),
      disconnect: vi.fn(),
    };
    node.gain.setTargetAtTime.mockImplementation((value: number) => {
      node.gain.value = value;
    });
    gainNodes.push(node);
    return node;
  }
  createDynamicsCompressor() {
    const node = {
      threshold: {},
      knee: {},
      ratio: {},
      attack: {},
      release: {},
      connect: vi.fn(),
      disconnect: vi.fn(),
    };
    limiterNodes.push(node);
    return node;
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
    const source = {
      frequency: { value: 0 },
      start: vi.fn(),
      stop: vi.fn(),
      disconnect: vi.fn(),
      connect: vi.fn((node: any) => node),
      onended: null,
    };
    clickNodes.push(source);
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
  decodedDuration = 10;
  nodes.length = 0;
  clickNodes.length = 0;
  gainNodes.length = 0;
  limiterNodes.length = 0;
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
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

it("imports audio helpers without evaluating the SoundTouch runtime", () => {
  expect(eagerlyImportedSoundTouch).toBe(false);
});

it("explains the secure origin requirement during preparation without AudioWorklet", async () => {
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
  await expect(player.load(stems, new AbortController().signal)).rejects.toThrow(
    "localhost or HTTPS",
  );
  expect(clock.decodeAudioData).toHaveBeenCalledTimes(stems.length);
  expect(player.duration).toBe(0);
  expect(soundTouchMock.register).not.toHaveBeenCalled();
  expect(soundTouchMock.nodes).toHaveLength(0);
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

  it("bounds click boost independently from stem gain", () => {
    expect(clickGain(-1)).toBe(0);
    expect(clickGain(1.5)).toBe(1.5);
    expect(clickGain(3)).toBe(2);
    expect(clickGain(Number.NaN)).toBe(DEFAULT_CLICK_VOLUME);
    expect(channelGain("guitar", mix)).toBe(1.5);
  });

  it("pre-compensates click pitch for the shared SoundTouch stage", () => {
    expect(clickInputFrequency(1760, 1, 0)).toBe(1760);
    expect(clickInputFrequency(1760, 0.5, 0)).toBe(880);
    expect(clickInputFrequency(1760, 1, 12)).toBe(880);
    expect(clickInputFrequency(1175, 1.25, -12)).toBe(2937.5);
  });
});

it("routes boosted click around the music master and through SoundTouch", async () => {
  const player = new MixerEngine();
  player.setMix({
    guitar: { ...mix.guitar, muted: true },
    drums: { ...mix.drums, volume: 0 },
  });
  player.setMaster(0);
  player.setClickVolume(2);
  player.setClickOptions(
    {
      beats: [0, 0.5, 1, 1.5],
      downbeats: [0],
      time_signature: 4,
    },
    0,
    true,
  );
  await player.load(stems, new AbortController().signal);
  await player.play();

  const [master, clickOutput] = gainNodes;
  expect(master.gain.value).toBe(0);
  expect(clickOutput.gain.value).toBe(2);
  expect(master.connect).toHaveBeenCalledWith(soundTouchMock.nodes[0]);
  expect(clickOutput.connect).toHaveBeenCalledWith(soundTouchMock.nodes[0]);
  expect(soundTouchMock.nodes[0].connect).toHaveBeenCalledWith(limiterNodes[0]);
  expect(clickOutput.connect).not.toHaveBeenCalledWith(limiterNodes[0]);
  expect(clickNodes).not.toHaveLength(0);
  expect(clickNodes[0].type).toBe("square");
  expect(clickNodes[0].start.mock.calls[0][0]).toBe(
    nodes[0].start.mock.calls[0][0],
  );
  expect(clickNodes[0].connect.mock.calls[0][0].connect).toHaveBeenCalledWith(
    clickOutput,
  );
  expect(
    clickNodes[0].connect.mock.calls[0][0].gain.setValueAtTime,
  ).toHaveBeenCalledWith(0.72, expect.closeTo(0.04));
  player.dispose();
});

it("updates the live click bus without changing the music master", async () => {
  const player = new MixerEngine();
  await player.load(stems, new AbortController().signal);
  player.setMaster(0.35);
  player.setClickVolume(1.75);

  expect(gainNodes[0].gain.setTargetAtTime).toHaveBeenCalledWith(
    0.35,
    clock.currentTime,
    0.015,
  );
  expect(gainNodes[1].gain.setTargetAtTime).toHaveBeenCalledWith(
    1.75,
    clock.currentTime,
    0.01,
  );
  expect(gainNodes[0].gain.setTargetAtTime).toHaveBeenCalledTimes(1);
  player.dispose();
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

it("uses one clock for rate-scaled count-in and music handoff without a duplicate", async () => {
  const player = new MixerEngine();
  await player.load(stems, new AbortController().signal);
  player.setClickOptions(
    {
      beats: [0, 0.5, 1, 1.5, 2, 2.5, 3],
      downbeats: [0, 2],
      time_signature: 4,
    },
    1,
    true,
  );
  player.setRate(0.5);
  player.seek(2);
  await player.play(true);
  expect(nodes[0].start.mock.calls[0]).toEqual([4.04, 2]);
  expect(clickNodes.map((node) => node.start.mock.calls[0][0])).toEqual(
    [0.04, 1.04, 2.04, 3.04].map((value) => expect.closeTo(value)),
  );
  clock.currentTime = 2.1;
  (player as any).schedule();
  expect(
    clickNodes.filter(
      (node) => Math.abs(node.start.mock.calls[0][0] - 4.04) < 1e-8,
    ),
  ).toHaveLength(1);
  expect(clickNodes[0].frequency.value).toBe(880);
  expect(gainNodes[1].gain.value).toBe(DEFAULT_CLICK_VOLUME);
  const countInGain = clickNodes[0].connect.mock.calls[0][0];
  expect(countInGain.gain.setValueAtTime).toHaveBeenCalledWith(
    0.72,
    expect.closeTo(0.04),
  );
  expect(countInGain.connect).toHaveBeenCalledWith(gainNodes[1]);
  player.dispose();
});

it("keeps loop clicks aligned across a slow boundary without duplicates", async () => {
  const player = new MixerEngine();
  await player.load(stems, new AbortController().signal);
  player.setClickOptions(
    {
      beats: [2, 2.25, 2.5, 2.75, 6, 6.25, 6.5, 6.75],
      downbeats: [2, 6],
      time_signature: 4,
    },
    0,
    true,
  );
  player.setLoopPlan(true, [
    { id: "early", name: "Early", a: 2, b: 2.5, enabled: true },
    { id: "late", name: "Late", a: 6, b: 6.5, enabled: true },
  ]);
  player.setRate(0.5);
  await player.play();

  expect(clickNodes.map((node) => node.start.mock.calls[0][0])).toEqual(
    [0.04, 0.54, 1.04, 1.54].map((value) => expect.closeTo(value)),
  );
  expect(clickNodes.map((node) => node.frequency.value)).toEqual([
    880, 587.5, 880, 587.5,
  ]);
  clock.currentTime = 1.1;
  (player as any).schedule();
  const starts = clickNodes.map((node) => node.start.mock.calls[0][0]);
  expect(starts.filter((at) => Math.abs(at - 2.04) < 1e-8)).toHaveLength(1);
  player.dispose();
});

it("cancels stale click lookahead and aligns a seek to the new source time", async () => {
  const player = new MixerEngine();
  await player.load(stems, new AbortController().signal);
  player.setClickOptions(
    {
      beats: Array.from({ length: 20 }, (_, index) => index * 0.5),
      downbeats: [0, 2, 4, 6, 8],
      time_signature: 4,
    },
    1,
    true,
  );
  await player.play(true);
  const staleClicks = [...clickNodes];

  player.seek(5);
  await vi.waitFor(() =>
    expect(clickNodes.length).toBeGreaterThan(staleClicks.length),
  );
  staleClicks.forEach((node) => expect(node.stop).toHaveBeenCalled());
  const resumedStem = nodes.at(-2);
  const resumedClicks = clickNodes.slice(staleClicks.length);
  expect(resumedStem.start.mock.calls[0][1]).toBe(5);
  expect(resumedClicks[0].start.mock.calls[0][0]).toBe(
    resumedStem.start.mock.calls[0][0],
  );
  expect(resumedClicks[0].frequency.value).toBe(1175);
  player.dispose();
});

it("recompensates already queued clicks after a live pitch change", async () => {
  const player = new MixerEngine();
  await player.load(stems, new AbortController().signal);
  player.setClickOptions(
    {
      beats: [0, 0.5, 1, 1.5],
      downbeats: [0],
      time_signature: 4,
    },
    0,
    true,
  );
  await player.play();
  expect(clickNodes[0].frequency.value).toBe(1760);
  expect(clickNodes[1].frequency.value).toBe(1175);

  player.setPitch(12);
  expect(clickNodes[0].frequency.value).toBe(880);
  expect(clickNodes[1].frequency.value).toBe(587.5);
  expect(soundTouchMock.nodes[0].pitchSemitones.value).toBe(12);
  player.dispose();
});

it("bounds continued click scheduling to the audio-clock lookahead", async () => {
  const player = new MixerEngine();
  await player.load(stems, new AbortController().signal);
  player.setClickOptions(
    {
      beats: Array.from({ length: 20 }, (_, index) => index * 0.5),
      downbeats: [0, 2, 4, 6, 8],
      time_signature: 4,
    },
    0,
    true,
  );
  await player.play();
  expect(clickNodes).toHaveLength(4);
  expect(clickNodes.at(-1).start.mock.calls[0][0]).toBeCloseTo(1.54);
  clock.currentTime = 1;
  (player as any).schedule();
  expect(clickNodes).toHaveLength(6);
  expect(clickNodes.at(-1).start.mock.calls[0][0]).toBeCloseTo(2.54);
  player.dispose();
});

it("does not repeat count-in on pause/resume and cancels queued clicks", async () => {
  const player = new MixerEngine();
  await player.load(stems, new AbortController().signal);
  player.setClickOptions(
    {
      beats: [0, 0.5, 1, 1.5, 2, 2.5],
      downbeats: [0, 2],
      time_signature: 4,
    },
    1,
    false,
  );
  await player.play(true);
  expect(clickNodes).toHaveLength(4);
  player.pause();
  clickNodes.forEach((node) => expect(node.stop).toHaveBeenCalled());
  const previous = clickNodes.length;
  await player.play(true);
  expect(clickNodes).toHaveLength(previous);
  player.dispose();
});

it("counts in again after an explicit stop", async () => {
  const player = new MixerEngine();
  await player.load(stems, new AbortController().signal);
  player.setClickOptions(
    {
      beats: [0, 0.5, 1, 1.5, 2],
      downbeats: [0, 2],
      time_signature: 4,
    },
    1,
    false,
  );
  await player.play(true);
  expect(clickNodes).toHaveLength(4);
  player.stop();
  player.seek(0);
  await player.play(true);
  expect(clickNodes).toHaveLength(8);
  player.dispose();
});

it("loops and accounts for speed on the shared timeline", async () => {
  const player = new MixerEngine();
  await player.load(stems, new AbortController().signal);
  player.setLoopPlan(true, [
    { id: "one", name: "One", a: 2, b: 4, enabled: true },
  ]);
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
  expect(soundTouchMock.register).toHaveBeenCalledTimes(1);
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
  expect(nodes).toHaveLength(stems.length);
  player.pause();
  nodes.forEach((source) => expect(source.stop).toHaveBeenLastCalledWith());
  resume();
  await play;
  expect(player.playing).toBe(false);
  expect(nodes).toHaveLength(stems.length);
  player.dispose();
});

it("schedules synchronously with prepared SoundTouch even if resume never resolves", async () => {
  vi.useFakeTimers();
  const categories: string[] = [];
  vi.stubGlobal("navigator", {
    audioSession: { set type(value: string) { categories.push(value); } },
  });
  const player = new MixerEngine();
  await player.load(stems, new AbortController().signal);
  expect(soundTouchMock.imported).toHaveBeenCalled();
  expect(soundTouchMock.register).toHaveBeenCalledTimes(1);
  expect(soundTouchMock.nodes).toHaveLength(0);
  clock.resume.mockImplementation(() => new Promise<void>(() => {}));

  const play = player.play();
  expect(clock.resume).toHaveBeenCalledTimes(1);
  expect(player.playing).toBe(true);
  expect(nodes).toHaveLength(stems.length);
  expect(nodes[0].start).toHaveBeenCalledWith(0.04, 0);
  expect(soundTouchMock.nodes).toHaveLength(1);
  expect(categories).toEqual(["playback", "ambient"]);
  await play;
  expect(categories).toEqual(["playback", "ambient"]);
  vi.runOnlyPendingTimers();
  expect(categories).toEqual(["playback", "ambient", "playback"]);

  player.pause();
  void player.play();
  expect(soundTouchMock.nodes).toHaveLength(2);
  player.seek(3);
  expect(nodes.at(-1).start).toHaveBeenCalledWith(0.04, 3);
  player.setRate(0.75);
  expect(nodes.at(-1).playbackRate.value).toBe(0.75);
  expect(soundTouchMock.register).toHaveBeenCalledTimes(1);
  player.dispose();
});

it("waits for worklet preparation before publishing a load and cancels a superseded load", async () => {
  let finishRegistration!: () => void;
  soundTouchMock.register.mockImplementationOnce(() => new Promise<void>((resolve) => {
    finishRegistration = resolve;
  }));
  const player = new MixerEngine();
  const controller = new AbortController();
  const firstLoad = player.load(stems, controller.signal);
  await vi.waitFor(() => expect(soundTouchMock.register).toHaveBeenCalledTimes(1));
  expect(player.duration).toBe(0);
  await player.play();
  expect(nodes).toHaveLength(0);

  controller.abort();
  const secondLoad = player.load([stems[0]], new AbortController().signal);
  await vi.waitFor(() => expect(clock.decodeAudioData).toHaveBeenCalledTimes(3));
  finishRegistration();
  await Promise.all([firstLoad, secondLoad]);
  expect(soundTouchMock.register).toHaveBeenCalledTimes(1);
  void player.play();
  expect(nodes).toHaveLength(1);
  expect(player.duration).toBe(10);
  player.dispose();
});

it("does not replace a seek's sources when an earlier resume resolves", async () => {
  const player = new MixerEngine();
  await player.load(stems, new AbortController().signal);
  let finishResume!: () => void;
  clock.resume.mockImplementationOnce(() => new Promise<void>((resolve) => {
    finishResume = resolve;
  }));
  void player.play();
  player.seek(4);
  expect(nodes).toHaveLength(4);
  expect(nodes[2].start).toHaveBeenCalledWith(0.04, 4);
  finishResume();
  await Promise.resolve();
  expect(nodes).toHaveLength(4);
  expect(player.playing).toBe(true);
  player.dispose();
});

it("attempts resume for Safari's interrupted state and contains resume failures", async () => {
  const player = new MixerEngine();
  await player.load(stems, new AbortController().signal);
  clock.state = "interrupted";
  clock.resume.mockRejectedValueOnce(new Error("Interrupted"));
  await player.play();
  expect(clock.resume).toHaveBeenCalledTimes(1);
  expect(nodes).toHaveLength(stems.length);
  player.pause();
  clock.resume.mockImplementationOnce(() => { throw new Error("Unavailable"); });
  await player.play();
  expect(player.playing).toBe(true);
  player.dispose();
});

it("reasserts playback on Play and foreground recovery without restarting paused music", async () => {
  vi.useFakeTimers();
  const categories: string[] = [];
  vi.stubGlobal("navigator", {
    audioSession: { set type(value: string) { categories.push(value); } },
  });
  const player = new MixerEngine();
  await player.load(stems, new AbortController().signal);
  expect(categories).toEqual(["playback"]);
  clock.state = "running";
  await player.play();
  expect(categories).toEqual(["playback", "ambient"]);
  vi.runOnlyPendingTimers();
  expect(categories).toEqual(["playback", "ambient", "playback"]);
  expect(clock.resume).not.toHaveBeenCalled();
  clock.state = "interrupted";
  player.handleVisibilityChange(false);
  expect(categories.at(-1)).toBe("ambient");
  vi.runOnlyPendingTimers();
  expect(categories.slice(-2)).toEqual(["ambient", "playback"]);
  expect(clock.resume).toHaveBeenCalledTimes(1);
  expect(nodes).toHaveLength(stems.length);
  player.pause();
  categories.length = 0;
  player.handleVisibilityChange(false);
  expect(categories).toEqual([]);
  expect(clock.resume).toHaveBeenCalledTimes(1);
  expect(player.playing).toBe(false);
  player.dispose();
});

it.each([true, false])("suspends and resumes a running context without changing music playback (%s)", async (playing) => {
  vi.useFakeTimers();
  const categories: string[] = [];
  vi.stubGlobal("navigator", {
    audioSession: { set type(value: string) { categories.push(value); } },
  });
  const player = new MixerEngine();
  await player.load(stems, new AbortController().signal);
  if (playing) await player.play();
  vi.runOnlyPendingTimers();
  categories.length = 0;
  clock.resume.mockClear();
  clock.state = "running";
  const sources = [...nodes];
  const stops = sources.map((source) => [...source.stop.mock.calls]);
  const processors = [...soundTouchMock.nodes];
  const gains = [...gainNodes];
  player.handleVisibilityChange(true);
  player.handleVisibilityChange(true);
  expect(clock.suspend).toHaveBeenCalledTimes(1);
  expect(player.playing).toBe(playing);
  player.handleVisibilityChange(false);
  expect(categories).toEqual(["ambient"]);
  expect(clock.resume).toHaveBeenCalledTimes(1);
  vi.runOnlyPendingTimers();
  expect(categories).toEqual(["ambient", "playback"]);
  player.handleVisibilityChange(false);
  expect(clock.resume).toHaveBeenCalledTimes(1);
  expect(player.playing).toBe(playing);
  expect(nodes).toEqual(sources);
  expect(soundTouchMock.nodes).toEqual(processors);
  expect(gainNodes).toEqual(gains);
  sources.forEach((source, index) => expect(source.stop.mock.calls).toEqual(stops[index]));
  if (!playing) expect(nodes).toHaveLength(0);
  player.dispose();
});

it("keeps music paused when paused during our visibility suspension", async () => {
  const player = new MixerEngine();
  await player.load(stems, new AbortController().signal);
  clock.state = "running";
  await player.play();
  player.handleVisibilityChange(true);
  player.pause();
  player.handleVisibilityChange(false);
  expect(clock.resume).toHaveBeenCalledTimes(1);
  expect(player.playing).toBe(false);
  expect(nodes).toHaveLength(stems.length);
  expect(soundTouchMock.nodes).toHaveLength(1);
  nodes.forEach((source) => expect(source.stop).toHaveBeenLastCalledWith());
  player.dispose();
});

it.each([true, false])("does not own or resume an already suspended context (%s)", async (playing) => {
  vi.useFakeTimers();
  const categories: string[] = [];
  vi.stubGlobal("navigator", {
    audioSession: { set type(value: string) { categories.push(value); } },
  });
  const player = new MixerEngine();
  await player.load(stems, new AbortController().signal);
  if (playing) await player.play();
  vi.runOnlyPendingTimers();
  categories.length = 0;
  clock.resume.mockClear();
  clock.state = "suspended";
  player.handleVisibilityChange(true);
  player.handleVisibilityChange(false);
  expect(clock.suspend).not.toHaveBeenCalled();
  expect(clock.resume).not.toHaveBeenCalled();
  expect(categories).toEqual([]);
  expect(player.playing).toBe(playing);
  player.dispose();
});

it("queues foreground resume while our background suspend is still pending", async () => {
  const player = new MixerEngine();
  await player.load(stems, new AbortController().signal);
  clock.state = "running";
  let finishSuspend!: () => void;
  clock.suspend.mockImplementationOnce(() => new Promise<void>((resolve) => {
    finishSuspend = resolve;
  }));
  player.handleVisibilityChange(true);
  player.handleVisibilityChange(true);
  player.handleVisibilityChange(false);
  expect(clock.suspend).toHaveBeenCalledTimes(1);
  expect(clock.resume).toHaveBeenCalledTimes(1);
  finishSuspend();
  await Promise.resolve();
  expect(nodes).toHaveLength(0);
  expect(player.playing).toBe(false);
  player.dispose();
});

it.each([true, false])("contains suspend failures and clears suspension ownership (throws: %s)", async (throws) => {
  const player = new MixerEngine();
  await player.load(stems, new AbortController().signal);
  clock.state = "running";
  clock.suspend.mockImplementationOnce(() => {
    if (throws) throw new Error("Unavailable");
    return Promise.reject(new Error("Unavailable"));
  });
  expect(() => player.handleVisibilityChange(true)).not.toThrow();
  await Promise.resolve();
  clock.state = "suspended";
  player.handleVisibilityChange(false);
  expect(clock.resume).not.toHaveBeenCalled();
  player.dispose();
});

it("forces ambient now and playback only on the next task", () => {
  vi.useFakeTimers();
  const categories: string[] = [];
  vi.stubGlobal("navigator", {
    audioSession: { set type(value: string) { categories.push(value); } },
  });
  reassertPlaybackSession(true);
  expect(categories).toEqual(["ambient"]);
  expect(vi.getTimerCount()).toBe(1);
  vi.runOnlyPendingTimers();
  expect(categories).toEqual(["ambient", "playback"]);
});

it("falls back to playback immediately when scheduling recovery fails", () => {
  const categories: string[] = [];
  vi.stubGlobal("navigator", {
    audioSession: { set type(value: string) { categories.push(value); } },
  });
  const schedule = vi.fn(() => { throw new Error("Unavailable"); });
  expect(() => reassertPlaybackSession(true, schedule)).not.toThrow();
  expect(categories).toEqual(["ambient", "playback"]);
});

it("feature-detects AudioSession and contains getter and category setter failures", () => {
  vi.useFakeTimers();
  vi.stubGlobal("navigator", undefined);
  expect(() => reassertPlaybackSession(true)).not.toThrow();
  vi.stubGlobal("navigator", {});
  expect(() => reassertPlaybackSession(true)).not.toThrow();
  vi.stubGlobal("navigator", {
    get audioSession() { throw new Error("Unavailable"); },
  });
  expect(() => reassertPlaybackSession(true)).not.toThrow();
  const categories: string[] = [];
  vi.stubGlobal("navigator", {
    audioSession: {
      set type(value: string) {
        categories.push(value);
        throw new Error("Unsupported category");
      },
    },
  });
  expect(() => reassertPlaybackSession(true)).not.toThrow();
  expect(categories).toEqual(["ambient"]);
  expect(() => vi.runOnlyPendingTimers()).not.toThrow();
  expect(categories).toEqual(["ambient", "playback"]);
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
  stale.forEach((node) => expect(node.stop).toHaveBeenCalledTimes(2));
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
  player.setLoopPlan(
    true,
    regions.map((loop) => ({ ...loop, enabled: false })),
  );
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
it.each([0.5, 1, 1.25])(
  "resynchronizes after a long scheduler delay at speed %s",
  async (rate) => {
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
    expect(nodes[count].stop.mock.calls[0][0]).toBeCloseTo(
      clock.currentTime + 0.5 / rate,
    );
    expect(player.position()).toBeCloseTo(expected);
    for (let i = count; i < nodes.length; i += stems.length) {
      expect(nodes[i].start.mock.calls[0][0]).toBeGreaterThanOrEqual(
        clock.currentTime,
      );
      expect(nodes[i].start.mock.calls).toEqual(nodes[i + 1].start.mock.calls);
    }
    player.dispose();
  },
);

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
  for (const invalid of ["", "NaN", "Infinity", "1:60", "-1", "1:2:3"])
    expect(parseTime(invalid)).toBeNull();
});

it.each([0.5, 0.75, 0.9, 1, 1.1, 1.25])(
  "counts into corrected Easy Lover with exact handoff at %s× through SoundTouch",
  async (rate) => {
    decodedDuration = 400;
    const player = new MixerEngine();
    await player.load(stems, new AbortController().signal);
    const grid = easyLoverCorrection.grid;
    const position = grid.beats[28]; // retained source index 38, corrected index 28
    player.setClickOptions(grid, 1, true);
    player.setRate(rate);
    player.setPitch(3);
    player.setClickVolume(1.4);
    player.seek(position);
    await player.play(true);
    const planned = countInClicks(grid, position, 1);
    expect(planned.map(click => click.songTime)).toEqual(grid.beats.slice(24, 28));
    const handoff = 0.04 + (position - planned[0].songTime) / rate;
    expect(nodes[0].start).toHaveBeenCalledWith(expect.closeTo(handoff), position);
    const countInNodes = clickNodes.slice(0, 4);
    expect(countInNodes.map(node => node.start.mock.calls[0][0])).toEqual(
      planned.map(click => expect.closeTo(0.04 + (click.songTime - planned[0].songTime) / rate)),
    );
    countInNodes.forEach((node, i) => {
      expect(node.frequency.value).toBeCloseTo(clickInputFrequency(planned[i].accent ? 1760 : 1175, rate, 3));
      expect(node.connect.mock.calls[0][0].connect).toHaveBeenCalledWith(gainNodes[1]);
    });
    expect(gainNodes[1].gain.value).toBe(1.4);
    expect(gainNodes[1].connect).toHaveBeenCalledWith(soundTouchMock.nodes[0]);
    clock.currentTime = handoff - 0.1;
    (player as any).schedule();
    expect(clickNodes.filter(node => Math.abs(node.start.mock.calls[0][0] - handoff) < 1e-7)).toHaveLength(1);
    player.dispose();
  },
);

it("switches source/corrected grids live, cancels stale clicks, and preserves transport settings", async () => {
  decodedDuration = 400;
  const player = new MixerEngine();
  await player.load(stems, new AbortController().signal);
  const raw = easyLover.source_analysis;
  const corrected = easyLoverCorrection.grid;
  player.setRate(0.75);
  player.setPitch(-2);
  player.setClickVolume(1.5);
  player.setClickOptions(raw, 1, true);
  player.seek(5);
  await player.play();
  clock.currentTime = 0.5;
  for (const grid of [corrected, raw]) {
    const position = player.position();
    const stale = [...clickNodes];
    player.setClickOptions(grid, 1, true);
    await vi.waitFor(() => expect(player.playing).toBe(true));
    stale.forEach(node => expect(node.stop).toHaveBeenCalled());
    expect(player.position()).toBeCloseTo(position);
    const fresh = clickNodes.slice(stale.length);
    const planned = gridClicksBetween(grid, position, position + 1.96 * 0.75);
    expect(fresh.map(node => node.start.mock.calls[0][0])).toEqual(
      planned.map(click => expect.closeTo(clock.currentTime + 0.04 + (click.songTime - position) / 0.75)),
    );
    expect(nodes.at(-1).playbackRate.value).toBe(0.75);
    expect(gainNodes[1].gain.value).toBe(1.5);
    expect(soundTouchMock.nodes.at(-1).pitchSemitones.value).toBe(-2);
  }
  player.dispose();
});

it.each([false, true])(
  "uses the selected %s correction mode for a two-bar count-in and exact stem handoff",
  async (enabled) => {
    vi.useFakeTimers();
    decodedDuration = 400;
    const player = new MixerEngine();
    try {
      await player.load(stems, new AbortController().signal);
      const raw = easyLover.source_analysis;
      const result = easyLoverCorrection as BeatCorrection;
      const grid = selectedClickGrid(raw, enabled, result)!;
      const position = result.grid.beats[28];
      // The same playhead is source index 38, corrected index 28. Assert the
      // selected eight pulses directly, independently of countInClicks.
      expect(raw.beats.indexOf(position)).toBe(38);
      const expectedTimes = enabled ? grid.beats.slice(20, 28) : grid.beats.slice(30, 38);
      const expectedAccents = enabled
        ? [true, false, false, false, true, false, false, false]
        : [false, false, true, false, false, false, true, false];
      const rate = 0.75;
      player.setRate(rate);
      player.setClickOptions(grid, 2, true);
      player.seek(position);
      await player.play(true);
      expect(clickNodes).toHaveLength(8);
      clickNodes.forEach((node, index) => {
        expect(node.start).toHaveBeenCalledWith(expect.closeTo(
          0.04 + (expectedTimes[index] - expectedTimes[0]) / rate,
        ));
        expect(node.frequency.value).toBeCloseTo(clickInputFrequency(
          expectedAccents[index] ? 1760 : 1175, rate, 0,
        ));
      });
      const handoff = 0.04 + (position - expectedTimes[0]) / rate;
      for (const node of nodes) {
        expect(node.start).toHaveBeenCalledWith(expect.closeTo(handoff), position);
      }
      expect(nodes).toHaveLength(stems.length);
      expect(player.position()).toBe(position);
      clock.currentTime = handoff - 0.1;
      vi.advanceTimersByTime(100);
      expect(clickNodes.filter(node => Math.abs(node.start.mock.calls[0][0] - handoff) < 1e-7))
        .toHaveLength(1);
    } finally {
      player.dispose();
    }
  },
);

// A timeout cannot interrupt a synchronous infinite loop. Bound calls to the
// real planner so a scheduler regression fails instead of hanging the runner.
function guardClickScheduler(player: MixerEngine) {
  const engine = player as any;
  const plan = engine.scheduleGridClicks.bind(player);
  const guard = vi.spyOn(engine, "scheduleGridClicks").mockImplementation((...args) => {
    if (guard.mock.calls.length > 200) throw new Error("Click scheduler failed to advance");
    return plan(...args);
  });
  return guard;
}

describe.each([false, true])("click seek with correction enabled=%s", correctionEnabled => {
  const grid = selectedClickGrid(easyLover.source_analysis, correctionEnabled,
    easyLoverCorrection as BeatCorrection)!;

  it("terminates the previously stalled 100.123s lookahead and yields to timers", async () => {
    decodedDuration = 400;
    const player = new MixerEngine();
    const guard = guardClickScheduler(player);
    try {
      await player.load(stems, new AbortController().signal);
      player.setClickOptions(grid, 1, true);
      player.seek(100.123);
      await player.play();
      expect(guard).toHaveBeenCalledTimes(1);
      expect((player as any).clickAt).toBe(2);
      expect((player as any).clickOffset).toBeCloseTo(102.083);
      await new Promise<void>(resolve => setTimeout(resolve, 0));
      expect(player.playing).toBe(true);
    } finally {
      player.dispose();
    }
  });

  it("seeks into an abstained gap without synthesizing or replaying clicks", async () => {
    decodedDuration = 400;
    const player = new MixerEngine();
    const guard = guardClickScheduler(player);
    const sparse = { ...grid, beats: grid.beats.filter((_, i) => i < 80 || i >= 90) };
    const target = grid.beats[84] + 0.123;
    try {
      await player.load(stems, new AbortController().signal);
      player.setClickOptions(sparse, 1, true);
      await player.play();
      const stale = [...clickNodes];
      guard.mockClear();
      player.seek(target);
      await vi.waitFor(() => expect(player.playing).toBe(true), { interval: 1 });
      expect(player.position()).toBe(target);
      expect(clickNodes).toHaveLength(stale.length);
      clock.currentTime = grid.beats[90] - target;
      guard.mockClear();
      (player as any).schedule();
      const planned = gridClicksBetween(sparse, target + clock.currentTime - 0.04,
        target + clock.currentTime - 0.04 + 2);
      expect(clickNodes.slice(stale.length).map(node => node.start.mock.calls[0][0])).toEqual(
        planned.map(click => expect.closeTo(0.04 + click.songTime - target)),
      );
      (player as any).schedule();
      expect(clickNodes).toHaveLength(stale.length + planned.length);
    } finally {
      player.dispose();
    }
  });

  it.each([0.5, 0.75, 0.9, 1, 1.1, 1.25])(
    "cancels stale clicks and schedules arbitrary live seeks exactly once at %s×",
    async rate => {
      decodedDuration = 400;
      const player = new MixerEngine();
      const guard = guardClickScheduler(player);
      try {
        await player.load(stems, new AbortController().signal);
        player.setClickOptions(grid, 1, true);
        player.setRate(rate);
        await player.play(true);
        const gap = (grid.beats[84] + grid.beats[85]) / 2;
        for (const target of [100.123, grid.beats[28], gap, 0.25,
          grid.beats.at(-1)! + 0.123, 399.99, 20.123, 0, 400]) {
          clock.currentTime += 0.137;
          const stale = [...clickNodes];
          const sourceCount = nodes.length;
          guard.mockClear();
          player.seek(target);
          await vi.waitFor(() => expect(player.playing).toBe(true), { interval: 1 });
          const offset = target === 400 ? 0 : target;
          expect(player.position()).toBe(offset);
          stale.forEach(node => expect(node.stop).toHaveBeenCalledTimes(2));
          const anchor = clock.currentTime + 0.04;
          expect(nodes[sourceCount].start).toHaveBeenCalledWith(anchor, offset);
          const planned = gridClicksBetween(grid, offset, Math.min(400, offset + 1.96 * rate));
          const fresh = clickNodes.slice(stale.length);
          expect(fresh.map(node => node.start.mock.calls[0][0])).toEqual(
            planned.map(click => expect.closeTo(anchor + (click.songTime - offset) / rate)),
          );
          expect(guard.mock.calls.length).toBeLessThanOrEqual(1);
          // An unchanged lookahead must neither create a burst nor repeat a beat.
          (player as any).schedule();
          expect(clickNodes).toHaveLength(stale.length + fresh.length);
        }
        const sourceCount = nodes.length;
        player.setRate(rate === 1.25 ? 0.5 : 1.25);
        await vi.waitFor(() => expect(player.playing).toBe(true), { interval: 1 });
        expect(nodes[sourceCount].playbackRate.value).toBe(player.rate);
        const previousCount = clickNodes.length;
        clock.currentTime += 1000.123;
        guard.mockClear();
        (player as any).schedule();
        expect(clickNodes.slice(previousCount).every(node => node.start.mock.calls[0][0] >= clock.currentTime)).toBe(true);
        expect((player as any).clickAt).toBe(Infinity);
      } finally {
        player.dispose();
      }
    },
  );

  it("advances across loop boundaries, gap seeks and speed changes without click bursts", async () => {
    decodedDuration = 400;
    const player = new MixerEngine();
    const guard = guardClickScheduler(player);
    const beat = grid.beats[120];
    const loops = [
      { id: "a", name: "A", a: beat, b: beat + 0.5, enabled: true },
      { id: "b", name: "B", a: 100.123, b: 100.673, enabled: true },
    ];
    try {
      await player.load(stems, new AbortController().signal);
      player.setClickOptions(grid, 1, true);
      player.setLoopPlan(true, loops);
      await player.play();
      for (const rate of [0.5, 1.25, 0.9]) {
        player.setRate(rate);
        await vi.waitFor(() => expect(player.playing).toBe(true), { interval: 1 });
        for (const target of [100.123, beat, beat + 0.125, beat + 0.5, 399.99]) {
          const stale = [...clickNodes];
          guard.mockClear();
          player.seek(target);
          await vi.waitFor(() => expect(player.playing).toBe(true), { interval: 1 });
          const offset = target >= 100.673 ? beat : target === beat + 0.5 ? 100.123 : target;
          expect(player.position()).toBe(offset);
          stale.forEach(node => expect(node.stop).toHaveBeenCalledTimes(2));
          const fresh = clickNodes.slice(stale.length);
          const starts = fresh.map(node => node.start.mock.calls[0][0]);
          expect(new Set(starts).size).toBe(starts.length);
          expect(starts.every(at => at >= clock.currentTime + 0.04 && at < clock.currentTime + 2)).toBe(true);
          expect(guard.mock.calls.length).toBeLessThan(10);
          (player as any).schedule();
          expect(clickNodes).toHaveLength(stale.length + fresh.length);
          const beforeDelay = clickNodes.length;
          clock.currentTime += 7200.063;
          guard.mockClear();
          (player as any).schedule();
          expect(guard.mock.calls.length).toBeLessThan(10);
          const resumed = clickNodes.slice(beforeDelay).map(node => node.start.mock.calls[0][0]);
          expect(new Set(resumed).size).toBe(resumed.length);
          expect(resumed.every(at => at >= clock.currentTime && at < clock.currentTime + 2)).toBe(true);
        }
      }
    } finally {
      player.dispose();
    }
  });
});
