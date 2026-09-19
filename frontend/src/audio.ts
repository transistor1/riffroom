import { SoundTouchNode } from "@soundtouchjs/audio-worklet";
// @ts-expect-error Vite resolves the package's documented processor asset import.
import soundTouchProcessorUrl from "@soundtouchjs/audio-worklet/processor?url";
import type { Mix, Stem } from "./types";

export function channelGain(name: string, mix: Mix): number {
  const channel = mix[name];
  if (
    !channel ||
    channel.muted ||
    (Object.values(mix).some((c) => c.solo) && !channel.solo)
  )
    return 0;
  return channel.volume;
}

/** All stems share one audio clock and start sample, including seeks and loops. */
export class MixerEngine {
  context: AudioContext | null = null;
  private master: GainNode | null = null;
  private limiter: DynamicsCompressorNode | null = null;
  private soundTouch: SoundTouchNode | null = null;
  private soundTouchRegistered = false;
  private buffers = new Map<string, AudioBuffer>();
  private sources = new Map<string, AudioBufferSourceNode>();
  private gains = new Map<string, GainNode>();
  private startedAt = 0;
  private offset = 0;
  private generation = 0;
  private playIntent = 0;
  playing = false;
  duration = 0;
  rate = 1;
  pitchSemitones = 0;
  loop: { a: number; b: number; enabled: boolean } = {
    a: 0,
    b: 0,
    enabled: false,
  };
  private mix: Mix = {};
  private masterVolume = 0.8;

  private init() {
    if (!this.context) {
      this.context = new AudioContext();
      this.master = this.context.createGain();
      // A gentle final limiter protects against boosted stems summing above full scale.
      const limiter = this.context.createDynamicsCompressor();
      limiter.threshold.value = -1;
      limiter.knee.value = 0;
      limiter.ratio.value = 20;
      limiter.attack.value = 0.003;
      limiter.release.value = 0.1;
      this.master.gain.value = this.masterVolume;
      limiter.connect(this.context.destination);
      this.limiter = limiter;
    }
    return this.context;
  }

  private async initSoundTouch(ctx: AudioContext) {
    if (!ctx.audioWorklet)
      throw new Error(
        "This browser does not support the audio processing Riffroom needs.",
      );
    if (!this.soundTouchRegistered) {
      await SoundTouchNode.register(ctx, soundTouchProcessorUrl);
      this.soundTouchRegistered = true;
    }
    if (this.soundTouch) return;
    const node = new SoundTouchNode({ context: ctx, outputChannelCount: 2 });
    node.setStretchParameters({
      sequenceMs: 80,
      seekWindowMs: 20,
      overlapMs: 12,
      quickSeek: false,
    });
    this.soundTouch = node;
    this.updateSoundTouchParameters();
    this.master!.connect(node).connect(this.limiter!);
  }

  private updateSoundTouchParameters() {
    if (!this.soundTouch) return;
    this.soundTouch.playbackRate.value = this.rate;
    this.soundTouch.pitchSemitones.value = this.pitchSemitones;
  }

  private resetSoundTouch() {
    if (!this.soundTouch) return;
    this.master?.disconnect(this.soundTouch);
    this.soundTouch.disconnect();
    this.soundTouch = null;
  }

  async load(stems: Stem[], signal: AbortSignal) {
    this.pause();
    this.offset = 0;
    this.duration = 0;
    const version = ++this.generation;
    this.buffers.clear();
    const ctx = this.init();
    await this.initSoundTouch(ctx);
    const decoded = new Map<string, AudioBuffer>();
    // Decode sequentially to keep memory peaks bounded on 16 GB machines.
    for (const stem of stems) {
      const response = await fetch(stem.url, { signal });
      if (!response.ok) throw new Error(`Couldn't load the ${stem.name} stem.`);
      const buffer = await ctx.decodeAudioData(await response.arrayBuffer());
      if (signal.aborted || version !== this.generation) return;
      decoded.set(stem.name, buffer);
    }
    if (signal.aborted || version !== this.generation) return;
    this.buffers = decoded;
    this.duration = Math.min(...[...decoded.values()].map((b) => b.duration));
  }

  setMix(mix: Mix) {
    this.mix = mix;
    if (!this.context) return;
    this.gains.forEach((gain, name) =>
      gain.gain.setTargetAtTime(
        channelGain(name, mix),
        this.context!.currentTime,
        0.015,
      ),
    );
  }
  setMaster(value: number) {
    this.masterVolume = value;
    this.master?.gain.setTargetAtTime(value, this.context!.currentTime, 0.015);
  }
  position() {
    if (!this.playing || !this.context) return this.offset;
    const elapsed =
      Math.max(0, this.context.currentTime - this.startedAt) * this.rate;
    let position = this.offset + elapsed;
    if (this.loop.enabled && position >= this.loop.b) {
      position =
        this.loop.a + ((position - this.loop.b) % (this.loop.b - this.loop.a));
    }
    return Math.min(position, this.duration);
  }
  async play() {
    if (this.playing || !this.buffers.size) return;
    const ctx = this.init();
    const intent = ++this.playIntent;
    await ctx.resume();
    if (intent !== this.playIntent || this.playing || !this.buffers.size)
      return;
    await this.initSoundTouch(ctx);
    if (intent !== this.playIntent || this.playing || !this.buffers.size)
      return;
    if (this.offset >= this.duration) this.offset = 0;
    if (
      this.loop.enabled &&
      (this.offset < this.loop.a || this.offset >= this.loop.b)
    )
      this.offset = this.loop.a;
    this.startedAt = ctx.currentTime + 0.04;
    this.playing = true;
    this.buffers.forEach((buffer, name) => {
      const source = ctx.createBufferSource();
      const gain = ctx.createGain();
      source.buffer = buffer;
      source.playbackRate.value = this.rate;
      source.loop = this.loop.enabled;
      source.loopStart = this.loop.a;
      source.loopEnd = this.loop.b;
      gain.gain.value = channelGain(name, this.mix);
      source.connect(gain).connect(this.master!);
      source.start(this.startedAt, this.offset);
      this.sources.set(name, source);
      this.gains.set(name, gain);
    });
  }
  pause() {
    this.playIntent++;
    this.offset = this.position();
    this.playing = false;
    this.sources.forEach((s) => {
      s.stop();
      s.disconnect();
    });
    this.sources.clear();
    this.gains.forEach((g) => g.disconnect());
    this.gains.clear();
    this.resetSoundTouch();
  }
  seek(position: number) {
    const resume = this.playing;
    this.pause();
    this.offset = Math.max(0, Math.min(position, this.duration));
    if (resume) void this.play();
  }
  setRate(rate: number) {
    const resume = this.playing;
    this.pause();
    this.rate = rate;
    if (resume) void this.play();
  }
  setPitch(semitones: number) {
    this.pitchSemitones = Math.max(-12, Math.min(12, semitones));
    this.updateSoundTouchParameters();
  }
  setLoop(loop: typeof this.loop) {
    const resume = this.playing;
    this.pause();
    this.loop = { ...loop, enabled: loop.enabled && loop.b - loop.a >= 0.25 };
    if (resume) void this.play();
  }
  dispose() {
    this.generation++;
    this.pause();
    this.buffers.clear();
    this.resetSoundTouch();
    this.master?.disconnect();
    this.master = null;
    this.limiter?.disconnect();
    this.limiter = null;
    void this.context?.close();
  }
}
