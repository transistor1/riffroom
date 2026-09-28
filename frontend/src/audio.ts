import type {
  SoundTouchNode,
  StretchParameters,
} from "@soundtouchjs/audio-worklet";
// @ts-expect-error Vite resolves the package's documented processor asset import.
import soundTouchProcessorUrl from "@soundtouchjs/audio-worklet/processor?url";
import type { BeatTimeline, MetronomeSettings, Mix, Stem } from "./types";

const standardStretchParameters: StretchParameters = {
  sequenceMs: 80,
  seekWindowMs: 20,
  overlapMs: 12,
  quickSeek: false,
};

/** Let SoundTouch lengthen its WSOLA windows at the most demanding speed. */
export function stretchParametersForRate(rate: number): StretchParameters {
  if (rate <= 0.55) {
    return {
      sequenceMs: 0,
      seekWindowMs: 0,
      overlapMs: 12,
      quickSeek: false,
    };
  }
  return standardStretchParameters;
}

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
  private timeline: BeatTimeline | null = null;
  private metronome: MetronomeSettings = {
    enabled: false,
    volume: 0.5,
    subdivision: 1,
    accent: true,
    countIn: false,
  };
  private clickNodes = new Set<OscillatorNode>();
  private clickGains = new Map<OscillatorNode, GainNode>();
  private clickTimer: ReturnType<typeof setInterval> | null = null;
  private scheduledUntil = 0;

  setBeatTimeline(timeline: BeatTimeline) {
    this.timeline = timeline;
    this.resyncClicks();
  }

  setMetronome(settings: MetronomeSettings) {
    this.metronome = { ...settings };
    this.resyncClicks();
  }

  private cancelClicks() {
    if (this.clickTimer !== null) clearInterval(this.clickTimer);
    this.clickTimer = null;
    for (const node of this.clickNodes) {
      node.onended = null;
      node.stop();
      node.disconnect();
      this.clickGains.get(node)?.disconnect();
    }
    this.clickNodes.clear();
    this.clickGains.clear();
  }

  private click(when: number, accent: boolean) {
    const ctx = this.context!;
    const node = ctx.createOscillator();
    const gain = ctx.createGain();
    node.frequency.value = accent ? 1500 : 1000;
    gain.gain.setValueAtTime(0, when);
    gain.gain.linearRampToValueAtTime(
      this.metronome.volume * this.masterVolume * 0.35,
      when + 0.002,
    );
    gain.gain.exponentialRampToValueAtTime(0.0001, when + 0.035);
    node.connect(gain).connect(this.limiter!);
    this.clickNodes.add(node);
    this.clickGains.set(node, gain);
    node.onended = () => {
      node.disconnect();
      gain.disconnect();
      this.clickNodes.delete(node);
      this.clickGains.delete(node);
    };
    node.start(when);
    node.stop(when + 0.04);
  }

  private localInterval() {
    const beats = this.timeline?.beats ?? [];
    const next = beats.findIndex((beat) => beat > this.offset);
    const index =
      next < 0 ? Math.max(0, beats.length - 2) : Math.max(0, next - 1);
    return beats[index + 1] - beats[index] || 60 / (this.timeline?.bpm || 120);
  }

  private resyncClicks() {
    this.cancelClicks();
    if (
      !this.playing ||
      !this.metronome.enabled ||
      !this.timeline?.beats.length
    )
      return;
    this.scheduledUntil = Math.max(this.context!.currentTime, this.startedAt);
    this.scheduleClicks();
    this.clickTimer = setInterval(() => this.scheduleClicks(), 25);
  }

  /** A short lookahead queues audio-clock events, never timer-clock clicks.
   * Split each window at loop boundaries so partial beats/subdivisions wrap too.
   */
  private scheduleClicks() {
    const ctx = this.context!;
    const end = ctx.currentTime + 0.15;
    // Count-in owns pre-roll; song windows must never precede the source start.
    let cursor = Math.max(this.scheduledUntil, ctx.currentTime, this.startedAt);
    const beats = this.timeline!.beats;
    while (cursor < end) {
      const elapsed = (cursor - this.startedAt) * this.rate;
      let song = this.offset + elapsed;
      if (this.loop.enabled && song >= this.loop.b)
        song =
          this.loop.a + ((song - this.loop.b) % (this.loop.b - this.loop.a));
      const boundary = this.loop.enabled ? this.loop.b : this.duration;
      const segmentEnd = Math.min(end, cursor + (boundary - song) / this.rate);
      if (segmentEnd <= cursor + 1e-9) break;
      const songEnd = song + (segmentEnd - cursor) * this.rate;
      // Binary search to avoid scanning an entire long song every 25 ms.
      let lo = 0,
        hi = beats.length;
      while (lo < hi) {
        const mid = (lo + hi) >>> 1;
        if (beats[mid] < song) lo = mid + 1;
        else hi = mid;
      }
      for (
        let i = Math.max(0, lo - 1);
        i < beats.length && beats[i] < songEnd;
        i++
      ) {
        const divisions = i + 1 < beats.length ? this.metronome.subdivision : 1;
        for (let sub = 0; sub < divisions; sub++) {
          const position =
            beats[i] +
            (sub ? ((beats[i + 1] - beats[i]) * sub) / divisions : 0);
          if (position >= song - 1e-9 && position < songEnd - 1e-9)
            this.click(
              cursor + (position - song) / this.rate,
              this.metronome.accent && i % 4 === 0 && sub === 0,
            );
        }
      }
      cursor = segmentEnd;
    }
    this.scheduledUntil = Math.max(this.scheduledUntil, end, this.startedAt);
  }

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
        "Riffroom's browser audio processing requires AudioWorklet. Open Riffroom on localhost or HTTPS to enable it.",
      );
    const { SoundTouchNode } = await import("@soundtouchjs/audio-worklet");
    if (!this.soundTouchRegistered) {
      await SoundTouchNode.register(ctx, soundTouchProcessorUrl);
      this.soundTouchRegistered = true;
    }
    if (this.soundTouch) return;
    const node = new SoundTouchNode({ context: ctx, outputChannelCount: 2 });
    node.setStretchParameters(stretchParametersForRate(this.rate));
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
  async play(countIn = true) {
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
    const preRoll =
      countIn &&
      this.metronome.enabled &&
      this.metronome.countIn &&
      this.timeline?.beats.length
        ? (4 * this.localInterval()) / this.rate
        : 0;
    const preRollStart = this.startedAt;
    this.startedAt += preRoll;
    this.playing = true;
    this.resyncClicks();
    if (preRoll) {
      for (let i = 0; i < 4; i++)
        this.click(
          preRollStart + (i * preRoll) / 4,
          this.metronome.accent && i === 0,
        );
    }
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
    this.cancelClicks();
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
    if (resume) void this.play(false);
  }
  setRate(rate: number) {
    const resume = this.playing;
    this.pause();
    this.rate = rate;
    if (resume) void this.play(false);
  }
  setPitch(semitones: number) {
    this.pitchSemitones = Math.max(-12, Math.min(12, semitones));
    this.updateSoundTouchParameters();
  }
  setLoop(loop: typeof this.loop) {
    const resume = this.playing;
    this.pause();
    this.loop = { ...loop, enabled: loop.enabled && loop.b - loop.a >= 0.25 };
    if (resume) void this.play(false);
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
