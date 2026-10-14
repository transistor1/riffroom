import type {
  SoundTouchNode,
  StretchParameters,
} from "@soundtouchjs/audio-worklet";
// @ts-expect-error Vite resolves the package's documented processor asset import.
import soundTouchProcessorUrl from "@soundtouchjs/audio-worklet/processor?url";
import type { BeatGrid, Mix, Stem, PracticeLoop } from "./types";
import { countInClicks, gridClicksBetween, type GridClick } from "./beatGrid";

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

/** Keep the public click control bounded while allowing a useful 2x boost. */
export const DEFAULT_CLICK_VOLUME = 1.25;

export function clickGain(value: number): number {
  return Number.isFinite(value)
    ? Math.max(0, Math.min(2, value))
    : DEFAULT_CLICK_VOLUME;
}

/**
 * SoundTouch removes the pitch change introduced by a rate-scaled source and
 * then applies the requested musical transpose. Clicks are oscillators rather
 * than rate-scaled buffers, so pre-compensate both factors to keep their
 * audible pitch fixed after they pass through the shared processor.
 */
export function clickInputFrequency(
  outputFrequency: number,
  rate: number,
  pitchSemitones: number,
): number {
  return (outputFrequency * rate) / 2 ** (pitchSemitones / 12);
}

/** All stems share one audio clock and start sample, including seeks and loops. */
export class MixerEngine {
  context: AudioContext | null = null;
  private master: GainNode | null = null;
  private clickOutput: GainNode | null = null;
  private limiter: DynamicsCompressorNode | null = null;
  private soundTouch: SoundTouchNode | null = null;
  private soundTouchRegistered = false;
  private buffers = new Map<string, AudioBuffer>();
  private sources = new Set<AudioBufferSourceNode>();
  private clickSources = new Map<OscillatorNode, number>();
  private gains = new Map<string, GainNode>();
  private startedAt = 0;
  private offset = 0;
  private generation = 0;
  private playIntent = 0;
  private wantsPlay = false;
  playing = false;
  duration = 0;
  rate = 1;
  pitchSemitones = 0;
  private route: PracticeLoop[] = [];
  private scheduler: ReturnType<typeof setInterval> | null = null;
  private nextAt = 0;
  private nextOffset = 0;
  private nextIndex = 0;
  private firstIndex = 0;
  private clickAt = 0;
  private clickOffset = 0;
  private clickIndex = 0;
  get looping() {
    return this.route.length > 0;
  }
  private mix: Mix = {};
  private masterVolume = 0.8;
  private clickVolume = DEFAULT_CLICK_VOLUME;
  private beatGrid: BeatGrid | null = null;
  private countInBars = 0;
  private clickEnabled = false;
  private resumeWithoutCountIn = false;

  private init() {
    if (!this.context) {
      this.context = new AudioContext();
      this.master = this.context.createGain();
      this.clickOutput = this.context.createGain();
      // A fast final limiter protects the independently boosted click and music sum.
      const limiter = this.context.createDynamicsCompressor();
      limiter.threshold.value = -3;
      limiter.knee.value = 0;
      limiter.ratio.value = 20;
      limiter.attack.value = 0.001;
      limiter.release.value = 0.08;
      this.master.gain.value = this.masterVolume;
      this.clickOutput.gain.value = this.clickVolume;
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
    // Keep the click independent of the music master, but put both buses
    // through the same tempo processor so its latency cannot separate them.
    this.master!.connect(node).connect(this.limiter!);
    this.clickOutput!.connect(node);
  }

  private updateSoundTouchParameters() {
    if (!this.soundTouch) return;
    this.soundTouch.playbackRate.value = this.rate;
    this.soundTouch.pitchSemitones.value = this.pitchSemitones;
  }

  private resetSoundTouch() {
    if (!this.soundTouch) return;
    this.master?.disconnect(this.soundTouch);
    this.clickOutput?.disconnect(this.soundTouch);
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
  setClickVolume(value: number) {
    this.clickVolume = clickGain(value);
    this.clickOutput?.gain.setTargetAtTime(
      this.clickVolume,
      this.context!.currentTime,
      0.01,
    );
  }
  position() {
    if (!this.playing || !this.context) return this.offset;
    const elapsed =
      Math.max(0, this.context.currentTime - this.startedAt) * this.rate;
    if (!this.looping) return Math.min(this.offset + elapsed, this.duration);
    const first = this.route[this.firstIndex];
    if (elapsed < first.b - this.offset) return this.offset + elapsed;
    let remaining =
      (elapsed - (first.b - this.offset)) %
      this.route.reduce((sum, loop) => sum + loop.b - loop.a, 0);
    for (let n = 1; n <= this.route.length; n++) {
      const loop = this.route[(this.firstIndex + n) % this.route.length];
      if (remaining < loop.b - loop.a) return loop.a + remaining;
      remaining -= loop.b - loop.a;
    }
    return first.a;
  }

  private schedule = () => {
    const ctx = this.context!;
    const now = ctx.currentTime;
    if (this.looping && this.nextAt < now) {
      // A delayed timer must skip missed audio, not start expired segments in a burst.
      // Reduce whole cycles first so even a long suspension costs at most one route.
      const cycle = this.route.reduce((sum, loop) => sum + loop.b - loop.a, 0);
      let missed = ((now - this.nextAt) * this.rate) % cycle;
      while (missed >= this.route[this.nextIndex].b - this.nextOffset) {
        missed -= this.route[this.nextIndex].b - this.nextOffset;
        this.nextIndex = (this.nextIndex + 1) % this.route.length;
        this.nextOffset = this.route[this.nextIndex].a;
      }
      this.nextOffset += missed;
      this.nextAt = now;
    }
    // Queue two seconds ahead; the audio clock, never this timer, triggers jumps.
    // The first music source is queued even when a long count-in puts it beyond
    // the normal lookahead window; both still start from the same audio clock.
    while (
      this.nextAt < now + 2 ||
      (this.sources.size === 0 && this.nextAt === this.startedAt)
    ) {
      const region = this.route[this.nextIndex];
      const end = region?.b ?? this.duration;
      const start = this.nextAt;
      const offset = this.nextOffset;
      const stop = start + (end - offset) / this.rate;
      this.buffers.forEach((buffer, name) => {
        const source = ctx.createBufferSource();
        source.buffer = buffer;
        source.playbackRate.value = this.rate;
        source.connect(this.gains.get(name)!);
        source.start(start, offset);
        source.stop(stop);
        this.sources.add(source);
        source.onended = () => {
          source.disconnect();
          this.sources.delete(source);
        };
      });
      if (!this.looping) {
        this.nextAt = Infinity;
        break;
      }
      this.nextIndex = (this.nextIndex + 1) % this.route.length;
      this.nextOffset = this.route[this.nextIndex].a;
      this.nextAt = stop;
    }
    this.scheduleClickLookahead(now);
  };

  private scheduleClickLookahead(now: number) {
    if (!this.clickEnabled || !this.beatGrid) return;
    if (this.clickAt < now) {
      if (!this.looping) {
        this.clickOffset += (now - this.clickAt) * this.rate;
        this.clickAt = now;
      } else {
        const cycle = this.route.reduce(
          (sum, loop) => sum + loop.b - loop.a,
          0,
        );
        let missed = ((now - this.clickAt) * this.rate) % cycle;
        while (missed >= this.route[this.clickIndex].b - this.clickOffset) {
          missed -= this.route[this.clickIndex].b - this.clickOffset;
          this.clickIndex = (this.clickIndex + 1) % this.route.length;
          this.clickOffset = this.route[this.clickIndex].a;
        }
        this.clickOffset += missed;
        this.clickAt = now;
      }
    }
    const horizon = now + 2;
    while (this.clickAt < horizon) {
      const region = this.route[this.clickIndex];
      const end = region?.b ?? this.duration;
      if (this.clickOffset >= end - 1e-9) {
        if (!this.looping) {
          this.clickAt = Infinity;
          break;
        }
        this.clickIndex = (this.clickIndex + 1) % this.route.length;
        this.clickOffset = this.route[this.clickIndex].a;
        continue;
      }
      const songEnd = Math.min(
        end,
        this.clickOffset + (horizon - this.clickAt) * this.rate,
      );
      this.scheduleGridClicks(
        gridClicksBetween(this.beatGrid, this.clickOffset, songEnd),
        this.clickAt,
        this.clickOffset,
      );
      this.clickAt += (songEnd - this.clickOffset) / this.rate;
      this.clickOffset = songEnd;
    }
  }

  private scheduleGridClicks(
    clicks: GridClick[],
    anchor: number,
    songAnchor: number,
  ) {
    const ctx = this.context!;
    for (const click of clicks) {
      const at = anchor + (click.songTime - songAnchor) / this.rate;
      if (at < ctx.currentTime - 1e-7) continue;
      const oscillator = ctx.createOscillator();
      const gain = ctx.createGain();
      // A short square transient cuts through dense recordings without requiring
      // the music master to be turned down. Accents remain easy to distinguish.
      oscillator.type = "square";
      const outputFrequency = click.accent ? 1760 : 1175;
      oscillator.frequency.value = clickInputFrequency(
        outputFrequency,
        this.rate,
        this.pitchSemitones,
      );
      gain.gain.setValueAtTime(click.accent ? 0.72 : 0.48, at);
      gain.gain.exponentialRampToValueAtTime(0.0001, at + 0.028);
      oscillator.connect(gain).connect(this.clickOutput!);
      oscillator.start(at);
      oscillator.stop(at + 0.032);
      this.clickSources.set(oscillator, outputFrequency);
      oscillator.onended = () => {
        oscillator.disconnect();
        gain.disconnect();
        this.clickSources.delete(oscillator);
      };
    }
  }

  setClickOptions(
    grid: BeatGrid | null,
    countInBars: number,
    enabled: boolean,
  ) {
    const resume = this.playing || this.wantsPlay;
    if (resume) this.pause();
    this.beatGrid = grid;
    this.countInBars = Math.max(0, Math.min(4, Math.floor(countInBars)));
    this.clickEnabled = enabled;
    if (resume) void this.play(false);
  }

  async play(requestCountIn = false) {
    if (this.playing || !this.buffers.size) return;
    this.wantsPlay = true;
    const ctx = this.init();
    const intent = ++this.playIntent;
    await ctx.resume();
    if (intent !== this.playIntent || this.playing || !this.buffers.size)
      return;
    await this.initSoundTouch(ctx);
    if (intent !== this.playIntent || this.playing || !this.buffers.size)
      return;
    if (this.offset >= this.duration) this.offset = 0;
    if (this.looping) {
      let index = this.route.findIndex(
        (loop) => this.offset >= loop.a && this.offset < loop.b,
      );
      if (index < 0) {
        index = this.route.findIndex((loop) => loop.a >= this.offset);
        if (index < 0) index = 0;
        this.offset = this.route[index].a;
      }
      this.firstIndex = index;
    }
    const useCountIn = requestCountIn && !this.resumeWithoutCountIn;
    const countIn = useCountIn
      ? countInClicks(this.beatGrid, this.offset, this.countInBars)
      : [];
    const lead = countIn.length
      ? (this.offset - countIn[0].songTime) / this.rate
      : 0;
    this.startedAt = ctx.currentTime + 0.04 + lead;
    if (countIn.length)
      this.scheduleGridClicks(countIn, this.startedAt, this.offset);
    this.resumeWithoutCountIn = false;
    this.playing = true;
    this.buffers.forEach((_buffer, name) => {
      const gain = ctx.createGain();
      gain.gain.value = channelGain(name, this.mix);
      gain.connect(this.master!);
      this.gains.set(name, gain);
    });
    this.nextAt = this.startedAt;
    this.nextOffset = this.offset;
    this.nextIndex = this.firstIndex;
    this.clickAt = this.startedAt;
    this.clickOffset = this.offset;
    this.clickIndex = this.firstIndex;
    this.schedule();
    if (this.looping || this.clickEnabled)
      this.scheduler = setInterval(this.schedule, 100);
  }

  pause() {
    this.wantsPlay = false;
    this.playIntent++;
    if (this.scheduler !== null) clearInterval(this.scheduler);
    this.scheduler = null;
    const wasPlaying = this.playing;
    this.offset = this.position();
    if (wasPlaying) this.resumeWithoutCountIn = true;
    this.playing = false;
    this.sources.forEach((s) => {
      s.stop();
      s.disconnect();
    });
    this.sources.clear();
    this.clickSources.forEach((_frequency, source) => {
      source.stop();
      source.disconnect();
    });
    this.clickSources.clear();
    this.gains.forEach((g) => g.disconnect());
    this.gains.clear();
    this.resetSoundTouch();
  }
  stop() {
    this.pause();
    this.resumeWithoutCountIn = false;
  }
  seek(position: number) {
    const resume = this.playing || this.wantsPlay;
    this.pause();
    this.offset = Math.max(0, Math.min(position, this.duration));
    if (!resume) this.resumeWithoutCountIn = false;
    if (resume) void this.play();
  }
  setRate(rate: number) {
    const resume = this.playing || this.wantsPlay;
    this.pause();
    this.rate = rate;
    if (resume) void this.play();
  }
  setPitch(semitones: number) {
    this.pitchSemitones = Math.max(-12, Math.min(12, semitones));
    this.updateSoundTouchParameters();
    // Keep lookahead clicks at their requested output pitch when a live pitch
    // edit changes the shared processor after their oscillators were created.
    this.clickSources.forEach((outputFrequency, source) => {
      source.frequency.value = clickInputFrequency(
        outputFrequency,
        this.rate,
        this.pitchSemitones,
      );
    });
  }
  setLoopPlan(mode: boolean, loops: PracticeLoop[]) {
    const resume = this.playing || this.wantsPlay;
    this.pause();
    this.route = mode
      ? loops
          .filter(
            (loop) =>
              loop.enabled &&
              Number.isFinite(loop.a) &&
              Number.isFinite(loop.b) &&
              loop.a >= 0 &&
              loop.b - loop.a >= 0.05 - 1e-9,
          )
          .map((loop) => ({ ...loop }))
          .sort((a, b) => a.a - b.a)
      : [];
    if (resume) void this.play();
  }
  dispose() {
    this.generation++;
    this.pause();
    this.buffers.clear();
    this.resetSoundTouch();
    this.master?.disconnect();
    this.master = null;
    this.clickOutput?.disconnect();
    this.clickOutput = null;
    this.limiter?.disconnect();
    this.limiter = null;
    void this.context?.close();
  }
}
