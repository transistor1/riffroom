import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowDownToLine,
  AudioLines,
  Check,
  Disc3,
  Drum,
  Guitar,
  Headphones,
  LoaderCircle,
  Music2,
  Pause,
  Piano,
  Play,
  Repeat2,
  RotateCcw,
  SkipBack,
  SlidersHorizontal,
  Volume2,
  Mic2,
} from "lucide-react";
import { MixerEngine } from "../audio";
import {
  time,
  type Channel,
  type Mix,
  type Run,
  type Stem,
  type Track,
} from "../types";
import Waveform from "./Waveform";

const icons: Record<string, typeof Guitar> = {
  guitar: Guitar,
  vocals: Mic2,
  drums: Drum,
  bass: AudioLines,
  piano: Piano,
  other: Music2,
  original: Disc3,
};
const colors: Record<string, string> = {
  guitar: "#d6ed8c",
  vocals: "#c4adf4",
  drums: "#f0b07a",
  bass: "#81c4dd",
  piano: "#e6c986",
  other: "#9eb9ad",
  original: "#aebec9",
};
const defaults = (stems: Stem[]): Mix =>
  Object.fromEntries(
    stems.map((s) => [s.name, { volume: 1, muted: false, solo: false }]),
  );
export default function Mixer({ track, run }: { track: Track; run?: Run }) {
  const original = !run;
  const stems = run?.stems ?? [
    {
      name: "original",
      file: "original.wav",
      url: `/api/tracks/${track.id}/original`,
      peaks: track.peaks,
    },
  ];
  const key = `${track.id}:${run?.id ?? "original"}`;
  const engine = useRef<MixerEngine | null>(null);
  const [mix, setMix] = useState<Mix>(() => {
    try {
      const saved = JSON.parse(
        localStorage.getItem(`riffroom:mix:${key}`) ?? "null",
      );
      const clean = defaults(stems);
      for (const name in clean) {
        const c = saved?.[name];
        if (c && Number.isFinite(c.volume))
          clean[name] = {
            volume: Math.max(0, Math.min(2, c.volume)),
            muted: !!c.muted,
            solo: !!c.solo,
          };
      }
      return clean;
    } catch {
      return defaults(stems);
    }
  });
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");
  const [playing, setPlaying] = useState(false);
  const [position, setPosition] = useState(0);
  const [master, setMaster] = useState(0.8);
  const [rate, setRate] = useState(1);
  const [pitch, setPitch] = useState(0);
  const [pitchInput, setPitchInput] = useState("0.0");
  const [loop, setLoop] = useState({ a: 0, b: track.duration, enabled: false });
  useEffect(() => {
    const player = new MixerEngine();
    engine.current = player;
    const controller = new AbortController();
    player.setMix(mix);
    player
      .load(stems, controller.signal)
      .then(() => {
        if (!controller.signal.aborted) setLoaded(true);
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(e.message);
      });
    const timer = window.setInterval(() => {
      const p = player.position();
      if (player.playing && !player.loop.enabled && p >= player.duration)
        player.pause();
      setPosition(p);
      setPlaying(player.playing);
    }, 50);
    return () => {
      controller.abort();
      clearInterval(timer);
      player.dispose();
    };
    // Parent remounts the mixer when a run changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => {
    engine.current?.setMix(mix);
    try {
      localStorage.setItem(`riffroom:mix:${key}`, JSON.stringify(mix));
    } catch {
      /* Storage may be disabled. */
    }
  }, [mix, key]);
  const toggle = useCallback(() => {
    if (!loaded) return;
    const player = engine.current!;
    if (player.playing) player.pause();
    else void player.play().catch((e) => setError(e.message));
    setPlaying(player.playing);
  }, [loaded]);
  useEffect(() => {
    const keyboard = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      if (
        ["INPUT", "SELECT", "BUTTON", "TEXTAREA"].includes(target.tagName) ||
        target.isContentEditable
      )
        return;
      if (e.code === "Space") {
        e.preventDefault();
        toggle();
      }
      if (e.code === "ArrowLeft") {
        e.preventDefault();
        engine.current?.seek(Math.max(0, position - 5));
      }
      if (e.code === "ArrowRight") {
        e.preventDefault();
        engine.current?.seek(position + 5);
      }
    };
    window.addEventListener("keydown", keyboard);
    return () => window.removeEventListener("keydown", keyboard);
  }, [toggle, position]);
  function change(name: string, values: Partial<Channel>) {
    setMix((current) => ({
      ...current,
      [name]: { ...current[name], ...values },
    }));
  }
  function updateLoop(next: typeof loop) {
    setLoop(next);
    engine.current?.setLoop(next);
  }
  function applyPitch(value: number) {
    const next = Math.round(Math.max(-12, Math.min(12, value)) * 10) / 10;
    setPitch(next);
    setPitchInput(next.toFixed(1));
    engine.current?.setPitch(next);
  }
  function commitPitchInput(value: string) {
    if (!value.trim()) {
      setPitchInput(pitch.toFixed(1));
      return;
    }
    const next = Number(value);
    if (Number.isFinite(next)) applyPitch(next);
    else setPitchInput(pitch.toFixed(1));
  }
  const soloed = Object.values(mix).some((c) => c.solo);
  const withoutGuitar =
    !original && !!mix.guitar && mix.guitar.muted && !soloed;
  return (
    <>
      {error && (
        <div className="error" role="alert">
          {error}
        </div>
      )}
      <section className="transport panel" aria-label="Playback">
        <div className="transport-top">
          <div className="transport-buttons">
            <button
              className="icon-button"
              title="Back to start"
              aria-label="Back to start"
              onClick={() => engine.current?.seek(loop.enabled ? loop.a : 0)}
            >
              <SkipBack size={19} />
            </button>
            <button
              className="play-button"
              aria-label={playing ? "Pause" : "Play"}
              disabled={!loaded}
              onClick={toggle}
            >
              {!loaded ? (
                <LoaderCircle className="spin" size={24} />
              ) : playing ? (
                <Pause size={23} fill="currentColor" />
              ) : (
                <Play size={23} fill="currentColor" />
              )}
            </button>
            <div className="time">
              <strong>{time(position)}</strong>
              <span> / {time(track.duration)}</span>
            </div>
          </div>
          <div className="transport-right">
            <span className="keyboard-hint">
              SPACE <span>play / pause</span>
            </span>
            <span className={`live-tag ${playing ? "is-playing" : ""}`}>
              <i />
              {playing ? "Playing" : loaded ? "Ready" : "Loading audio"}
            </span>
          </div>
        </div>
        <div className="timeline">
          <Waveform
            peaks={track.peaks}
            progress={position / track.duration}
            color="#cfdfa3"
          />
          <input
            aria-label="Seek"
            type="range"
            min="0"
            max={track.duration}
            step="0.05"
            value={position}
            onChange={(e) => {
              const p = +e.target.value;
              engine.current?.seek(p);
              setPosition(p);
            }}
          />
          <div
            className="playhead"
            style={{ left: `${(position / track.duration) * 100}%` }}
          />
          {loop.enabled && (
            <div
              className="loop-region"
              style={{
                left: `${(loop.a / track.duration) * 100}%`,
                width: `${((loop.b - loop.a) / track.duration) * 100}%`,
              }}
            />
          )}
        </div>
        <div className="timeline-labels">
          <span>0:00</span>
          <span>{time(track.duration / 4)}</span>
          <span>{time(track.duration / 2)}</span>
          <span>{time(track.duration * 0.75)}</span>
          <span>{time(track.duration)}</span>
        </div>
        <div className="practice-controls">
          <div className="loop-controls">
            <button
              className={
                loop.enabled ? "small-button selected" : "small-button"
              }
              onClick={() => updateLoop({ ...loop, enabled: !loop.enabled })}
              aria-pressed={loop.enabled}
            >
              <Repeat2 size={15} /> Loop
            </button>
            <button
              className="marker"
              title="Set loop start at playhead"
              onClick={() =>
                updateLoop({ ...loop, a: Math.min(position, loop.b - 0.25) })
              }
            >
              A <span>{time(loop.a)}</span>
            </button>
            <button
              className="marker"
              title="Set loop end at playhead"
              onClick={() =>
                updateLoop({
                  ...loop,
                  b: Math.min(
                    track.duration,
                    Math.max(position, loop.a + 0.25),
                  ),
                })
              }
            >
              B <span>{time(loop.b)}</span>
            </button>
            <button
              className="icon-button"
              aria-label="Reset loop"
              title="Reset loop"
              onClick={() =>
                updateLoop({ a: 0, b: track.duration, enabled: false })
              }
            >
              <RotateCcw size={13} />
            </button>
          </div>
          <div className="playback-adjustments">
            <label className="speed">
              Speed{" "}
              <select
                value={rate}
                onChange={(e) => {
                  const value = +e.target.value;
                  setRate(value);
                  engine.current?.setRate(value);
                }}
              >
                {[0.5, 0.75, 0.9, 1, 1.1, 1.25].map((r) => (
                  <option key={r} value={r}>
                    {r}×
                  </option>
                ))}
              </select>
            </label>
            <div className="pitch">
              <span>Pitch</span>
              <input
                className="pitch-slider"
                aria-label="Pitch"
                type="range"
                min="-12"
                max="12"
                step="0.1"
                value={pitch}
                onChange={(e) => applyPitch(+e.target.value)}
              />
              <input
                className="pitch-value"
                aria-label="Exact pitch in semitones"
                title="Exact pitch in semitones"
                type="number"
                inputMode="decimal"
                min="-12"
                max="12"
                step="0.1"
                value={pitchInput}
                onChange={(e) => setPitchInput(e.target.value)}
                onBlur={(e) => commitPitchInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    commitPitchInput(e.currentTarget.value);
                  }
                }}
              />
              <span className="pitch-unit">st</span>
              <button
                className="pitch-reset"
                aria-label="Reset pitch to zero"
                title="Reset pitch to zero"
                type="button"
                onClick={() => applyPitch(0)}
              >
                <RotateCcw size={13} />
              </button>
            </div>
          </div>
        </div>
      </section>
      <div className="section-heading">
        <div>
          <h2>{original ? "Original track" : "Stem mixer"}</h2>
          <span>
            {original
              ? "Listen while your stems are being prepared"
              : "Make room for your guitar"}
          </span>
        </div>
        <button className="text-button" onClick={() => setMix(defaults(stems))}>
          <RotateCcw size={14} /> Reset mix
        </button>
      </div>
      {!original && (
        <div className="presets">
          <button
            className={`preset ${withoutGuitar ? "selected" : ""}`}
            onClick={() => {
              const next = defaults(stems);
              if (next.guitar) next.guitar.muted = true;
              setMix(next);
            }}
            disabled={!mix.guitar}
          >
            <Guitar size={16} /> Play guitar with the band
            {withoutGuitar && <Check size={14} />}
          </button>
          <button
            className="preset"
            disabled={!mix.guitar}
            onClick={() => {
              const next = defaults(stems);
              if (next.guitar) next.guitar.solo = true;
              setMix(next);
            }}
          >
            <Headphones size={16} /> Hear just the guitar
          </button>
        </div>
      )}
      <div className="stem-list">
        {stems.map((stem) => {
          const c = mix[stem.name],
            Icon = icons[stem.name] ?? Music2,
            color = colors[stem.name] ?? "#aebec9";
          const silent = c.muted || (soloed && !c.solo);
          return (
            <article
              className={`stem-row ${silent ? "is-muted" : ""}`}
              key={stem.name}
              style={{ "--stem-color": color } as React.CSSProperties}
            >
              <div className="stem-icon">
                <Icon size={21} />
              </div>
              <div className="stem-name">
                <strong>{stem.name}</strong>
                <span>{c.solo ? "Solo" : silent ? "Muted" : "Stereo"}</span>
              </div>
              <div className="stem-wave">
                <Waveform
                  peaks={stem.peaks}
                  color={color}
                  progress={position / track.duration}
                />
              </div>
              <div className="stem-actions">
                <button
                  className={
                    c.muted ? "channel-button muted" : "channel-button"
                  }
                  aria-label={`Mute ${stem.name}`}
                  aria-pressed={c.muted}
                  onClick={() => change(stem.name, { muted: !c.muted })}
                >
                  M
                </button>
                <button
                  className={c.solo ? "channel-button solo" : "channel-button"}
                  aria-label={`Solo ${stem.name}`}
                  aria-pressed={c.solo}
                  onClick={() => change(stem.name, { solo: !c.solo })}
                >
                  S
                </button>
              </div>
              <div className="stem-volume">
                <input
                  aria-label={`${stem.name} volume`}
                  type="range"
                  min="0"
                  max="2"
                  step="0.01"
                  value={c.volume}
                  onChange={(e) =>
                    change(stem.name, { volume: +e.target.value })
                  }
                />
                <span>{Math.round(c.volume * 100)}%</span>
              </div>
              <a
                className="icon-button download"
                href={stem.url}
                download={`${track.title}-${stem.name}.wav`}
                title={`Download ${stem.name}`}
                aria-label={`Download ${stem.name}`}
              >
                <ArrowDownToLine size={15} />
              </a>
            </article>
          );
        })}
      </div>
      <div className="master">
        <span>
          <SlidersHorizontal size={15} /> Master output
        </span>
        <div>
          <Volume2 size={17} />
          <input
            aria-label="Master volume"
            type="range"
            min="0"
            max="1"
            step=".01"
            value={master}
            onChange={(e) => {
              setMaster(+e.target.value);
              engine.current?.setMaster(+e.target.value);
            }}
          />
          <span>{Math.round(master * 100)}%</span>
        </div>
      </div>
      <p className="mixer-note">
        <Headphones size={14} />
        {original
          ? "You can listen to the original while separation runs in the background."
          : "Separation can leave a little bleed. Compare models to find the best fit for this song."}
      </p>
    </>
  );
}
