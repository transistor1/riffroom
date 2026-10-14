import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowDownToLine,
  AudioLines,
  Check,
  ChevronDown,
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
  Split,
  Trash2,
  Volume2,
  Mic2,
} from "lucide-react";
import { api, loadPractice, savePractice } from "../api";
import { DEFAULT_CLICK_VOLUME, MixerEngine } from "../audio";
import {
  loadCorrectionPreference, saveCorrectionPreference, selectedClickGrid,
  validateCorrection, type BeatCorrection,
} from "../beatCorrection";
import {
  time,
  preciseTime,
  parseTime,
  type PracticeLoop,
  type Channel,
  type Mix,
  type Model,
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

export function mixForStems(saved: Mix, stems: Stem[]): Mix {
  const mix = defaults(stems);
  for (const name in mix) {
    const channel = saved[name];
    if (channel && Number.isFinite(channel.volume)) {
      mix[name] = {
        volume: Math.max(0, Math.min(2, channel.volume)),
        muted: !!channel.muted,
        solo: !!channel.solo,
      };
    }
  }
  return mix;
}

export function preserveStemMix(saved: Mix, stems: Stem[]): Mix {
  const visible = mixForStems(saved, stems);
  return Object.keys(visible).every((name) => saved[name])
    ? saved
    : { ...saved, ...visible };
}

export async function reloadMixerGraph(
  player: MixerEngine,
  stems: Stem[],
  mix: Mix,
  signal: AbortSignal,
  resumeAt: number,
): Promise<number | null> {
  player.setMix(mix);
  await player.load(stems, signal);
  if (signal.aborted) return null;
  const restored = Math.min(resumeAt, player.duration);
  player.seek(restored);
  return restored;
}

export type EffectiveStem = Stem & {
  displayName: string;
  sourceRunId: string;
  sourceStemName: string;
  logicalPart: string;
  depth: number;
  context: string;
};

const genericStemNames = new Set([
  "other",
  "instrumental",
  "music",
  "no_vocals",
  "karaoke",
]);

const normalizedStemName = (name: string) =>
  name
    .trim()
    .toLowerCase()
    .replace(/[\s-]+/g, "_");

export function derivePerformanceParts(root: Run): string[] {
  return root.stems
    .map((stem) => stem.name)
    .filter((name) => !genericStemNames.has(normalizedStemName(name)));
}

export function performancePartPreferenceKey(trackId: string): string {
  return `riffroom:performance-part:${trackId}`;
}

type PreferenceStorage = Pick<Storage, "getItem" | "setItem">;

export function chooseInitialPerformancePart(
  availableParts: string[],
): string | null {
  return (
    availableParts.find((part) => normalizedStemName(part) === "guitar") ??
    availableParts[0] ??
    null
  );
}

export function loadPerformancePartPreference(
  trackId: string,
  availableParts: string[],
  storage: PreferenceStorage,
): string | null {
  const key = performancePartPreferenceKey(trackId);
  const stored = storage.getItem(key);
  if (stored) return stored;
  const initial = chooseInitialPerformancePart(availableParts);
  if (initial) storage.setItem(key, initial);
  return initial;
}

export function savePerformancePartPreference(
  trackId: string,
  part: string,
  storage: PreferenceStorage,
) {
  storage.setItem(performancePartPreferenceKey(trackId), part);
}

export function isPerformancePartAvailable(
  preferredPart: string | null,
  availableParts: string[],
): boolean {
  return !!preferredPart && availableParts.includes(preferredPart);
}

const partLabel = (part: string) =>
  normalizedStemName(part).replaceAll("_", " ");

export function performancePartCopy(part: string): {
  primary: string;
  secondary: string;
} {
  const label = partLabel(part);
  return {
    primary:
      normalizedStemName(part) === "vocals"
        ? "Sing with the band"
        : `Play ${label} with the band`,
    secondary: `Hear just the ${label}`,
  };
}

export type PerformanceShortcutMode =
  | "none"
  | "play-with-band"
  | "hear-just";

export type PerformanceShortcutState = {
  mode: PerformanceShortcutMode;
  part: string | null;
  previous: {
    muted: Record<string, boolean>;
    solo: Record<string, boolean>;
  };
};

export type PerformanceShortcutResult = {
  mix: Mix;
  shortcut: PerformanceShortcutState;
};

export const noPerformanceShortcut = (): PerformanceShortcutState => ({
  mode: "none",
  part: null,
  previous: { muted: {}, solo: {} },
});

export function restorePerformanceShortcut(
  mix: Mix,
  shortcut: PerformanceShortcutState,
): Mix {
  if (shortcut.mode === "none") return mix;
  let next = mix;
  for (const field of ["muted", "solo"] as const) {
    for (const [name, value] of Object.entries(shortcut.previous[field])) {
      if (!mix[name]) continue;
      if (next === mix) next = { ...mix };
      next[name] = { ...next[name], [field]: value };
    }
  }
  return next;
}

export function transitionPerformanceShortcut(
  mix: Mix,
  stems: EffectiveStem[],
  shortcut: PerformanceShortcutState,
  mode: PerformanceShortcutMode,
  part: string,
): PerformanceShortcutResult {
  const restored = restorePerformanceShortcut(mix, shortcut);
  if (mode === "none") {
    return { mix: restored, shortcut: noPerformanceShortcut() };
  }

  const next = { ...restored };
  const previous: PerformanceShortcutState["previous"] = {
    muted: {},
    solo: {},
  };
  if (mode === "hear-just") {
    for (const [name, channel] of Object.entries(restored)) {
      previous.solo[name] = channel.solo;
    }
  }
  for (const stem of stems) {
    const channel = restored[stem.name];
    if (!channel) continue;
    if (mode === "play-with-band") {
      if (stem.logicalPart !== part) continue;
      previous.muted[stem.name] = channel.muted;
      next[stem.name] = { ...channel, muted: true };
    } else {
      if (stem.logicalPart === part) {
        previous.muted[stem.name] = channel.muted;
      }
      next[stem.name] = {
        ...channel,
        muted: stem.logicalPart === part ? false : channel.muted,
        solo: stem.logicalPart === part,
      };
    }
  }
  return { mix: next, shortcut: { mode, part, previous } };
}

export function retargetPerformanceShortcut(
  mix: Mix,
  stems: EffectiveStem[],
  shortcut: PerformanceShortcutState,
  part: string,
): PerformanceShortcutResult {
  if (shortcut.mode === "none") return { mix, shortcut };
  return transitionPerformanceShortcut(
    mix,
    stems,
    shortcut,
    shortcut.mode,
    part,
  );
}

export function applyManualChannelChange(
  mix: Mix,
  stems: EffectiveStem[],
  shortcut: PerformanceShortcutState,
  name: string,
  values: Partial<Channel>,
): PerformanceShortcutResult {
  const selectedFamilyMuteChanged =
    values.muted !== undefined &&
    stems.some(
      (stem) => stem.name === name && stem.logicalPart === shortcut.part,
    );
  const invalidatesShortcut =
    shortcut.mode !== "none" &&
    (values.solo !== undefined || selectedFamilyMuteChanged);
  const baseline = invalidatesShortcut
    ? restorePerformanceShortcut(mix, shortcut)
    : mix;
  return {
    mix: {
      ...baseline,
      [name]: { ...baseline[name], ...values },
    },
    shortcut: invalidatesShortcut ? noPerformanceShortcut() : shortcut,
  };
}

export type ExpansionPoint = {
  parentRunId: string;
  parentStemName: string;
  context: string;
  activeChildId: string | null;
  children: Run[];
};

export function resolveEffectiveMixer(
  track: Track,
  root: Run,
): { stems: EffectiveStem[]; expansions: ExpansionPoint[] } {
  const runs = new Map(
    track.runs.map((candidate) => [candidate.id, candidate]),
  );
  const stems: EffectiveStem[] = [];
  const expansions: ExpansionPoint[] = [];

  function visit(
    run: Run,
    stem: Stem,
    depth: number,
    context: string,
    ancestors: Set<string>,
    logicalPart: string,
  ) {
    const source = {
      type: "stem",
      run_id: run.id,
      stem_name: stem.name,
    } as const;
    const children = track.runs.filter(
      (candidate) =>
        candidate.source?.type === "stem" &&
        candidate.source.run_id === source.run_id &&
        candidate.source.stem_name === source.stem_name,
    );
    const selectedId = run.active_children?.[stem.name] ?? null;
    const selected = selectedId ? runs.get(selectedId) : undefined;
    const active =
      selected?.source?.type === "stem" &&
      selected.source.run_id === run.id &&
      selected.source.stem_name === stem.name &&
      !ancestors.has(selected.id)
        ? selected
        : undefined;
    if (children.length || active) {
      expansions.push({
        parentRunId: run.id,
        parentStemName: stem.name,
        context,
        activeChildId: active?.id ?? null,
        children,
      });
    }
    if (active) {
      const nextAncestors = new Set(ancestors).add(active.id);
      for (const childStem of active.stems) {
        visit(
          active,
          childStem,
          depth + 1,
          `${context} › ${childStem.name}`,
          nextAncestors,
          logicalPart,
        );
      }
      return;
    }
    stems.push({
      ...stem,
      name: depth === 0 ? stem.name : `${run.id}:${stem.name}`,
      displayName: stem.name,
      sourceRunId: run.id,
      sourceStemName: stem.name,
      logicalPart,
      depth,
      context,
    });
  }

  for (const stem of root.stems)
    visit(root, stem, 0, stem.name, new Set([root.id]), stem.name);
  return { stems, expansions };
}

type MixerProps = {
  track: Track;
  run?: Run;
  models?: Model[];
  modelCatalog?: Model[];
  busy?: boolean;
  onSeparateStem?: (runId: string, stemName: string, modelId: string) => void;
  onSelectExpansion?: (
    runId: string,
    stemName: string,
    childId: string | null,
  ) => void;
  onDeleteRun?: (runId: string) => void;
};

export default function Mixer({
  track,
  run,
  models = [],
  modelCatalog = models,
  busy = false,
  onSeparateStem,
  onSelectExpansion,
  onDeleteRun,
}: MixerProps) {
  const original = !run;
  const resolved = run ? resolveEffectiveMixer(track, run) : null;
  const stems = resolved?.stems ?? [
    {
      name: "original",
      file: "original.wav",
      url: `/api/tracks/${track.id}/original`,
      peaks: track.peaks,
    },
  ];
  const availableParts = run ? derivePerformanceParts(run) : [];
  const key = `${track.id}:${run?.id ?? "original"}`;
  const engine = useRef<MixerEngine | null>(null);
  const [mix, setMix] = useState<Mix>(() => {
    try {
      const saved = JSON.parse(
        localStorage.getItem(`riffroom:mix:${key}`) ?? "null",
      );
      return { ...(saved ?? {}), ...mixForStems(saved ?? {}, stems) };
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
  const [countInBars, setCountInBars] = useState(2);
  const [clickEnabled, setClickEnabled] = useState(false);
  const [clickVolume, setClickVolume] = useState(DEFAULT_CLICK_VOLUME);
  const [correctionEnabled, setCorrectionEnabled] = useState(() => loadCorrectionPreference(track.id));
  const [correction, setCorrection] = useState<{ key: string; result: BeatCorrection } | null>(null);
  const [correctionError, setCorrectionError] = useState<{ key: string; message: string } | null>(null);
  const [correctionRetry, setCorrectionRetry] = useState(0);
  const [loops, setLoops] = useState<PracticeLoop[]>(track.practice?.loops ?? []);
  const [loopMode, setLoopMode] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [saveError, setSaveError] = useState("");
  const [splitModels, setSplitModels] = useState<Record<string, string>>({});
  const [preferredPart, setPreferredPart] = useState<string | null>(() => {
    if (!run) return null;
    try {
      return loadPerformancePartPreference(
        track.id,
        availableParts,
        localStorage,
      );
    } catch {
      return chooseInitialPerformancePart(availableParts);
    }
  });
  const [partMenuOpen, setPartMenuOpen] = useState(false);
  const [shortcut, setShortcutState] = useState<PerformanceShortcutState>(
    noPerformanceShortcut,
  );
  const shortcutRef = useRef(shortcut);
  const effectiveMix = mixForStems(mix, stems);
  const mixRef = useRef(effectiveMix);
  const positionRef = useRef(position);
  mixRef.current = effectiveMix;
  positionRef.current = position;
  const graphKey = stems.map((stem) => `${stem.name}:${stem.url}`).join("|");
  const edited = useRef(false);
  const pending = useRef<PracticeLoop[] | null>(null);
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const selected = loops.find(loop => loop.id === selectedId);
  const [beatRequestError, setBeatRequestError] = useState("");
  const [retryingBeats, setRetryingBeats] = useState(false);
  const beatAnalysis = track.beat_analysis;
  useEffect(() => {
    if (beatAnalysis?.status) {
      setBeatRequestError("");
      return;
    }
    const controller = new AbortController();
    void api(`/tracks/${track.id}/beats/prepare`, { method: "POST", signal: controller.signal })
      .catch(reason => {
        if (!controller.signal.aborted) setBeatRequestError(`${reason.message} Reopen the song to retry beat preparation.`);
      });
    return () => controller.abort();
  }, [track.id, beatAnalysis?.status]);
  const rawBeatGrid = beatAnalysis?.status === "ready" && beatAnalysis.beats &&
    beatAnalysis.downbeats && beatAnalysis.time_signature
    ? { beats: beatAnalysis.beats, downbeats: beatAnalysis.downbeats,
        time_signature: beatAnalysis.time_signature }
    : null;
  const sourceKey = `${track.id}:${JSON.stringify(beatAnalysis)}`;
  const currentCorrection = correction?.key === sourceKey ? correction.result : null;
  const currentCorrectionError = correctionError?.key === sourceKey ? correctionError.message : "";
  const correctionDescription = currentCorrectionError
    ? `Correction failed: ${currentCorrectionError} ${correctionEnabled
      ? "Click and count-in unavailable; turn correction off or retry."
      : "Source grid in use; retry available."}`
    : !currentCorrection
      ? correctionEnabled
        ? "Preparing correction; click and count-in unavailable. Turn correction off to use the source grid."
        : "Preparing correction; source grid in use."
      : !correctionEnabled ? "Correction off; source grid in use."
      : currentCorrection.status === "applied" ? "Beat repair applied."
      : "No confident repair; source grid unchanged.";
  const beatGrid = selectedClickGrid(rawBeatGrid, correctionEnabled, currentCorrection);
  useEffect(() => {
    setCorrectionEnabled(loadCorrectionPreference(track.id));
  }, [track.id]);
  useEffect(() => {
    if (!rawBeatGrid || !beatAnalysis) return;
    const controller = new AbortController();
    setCorrectionError(null);
    setCorrection(null);
    void api<BeatCorrection>(`/tracks/${track.id}/beats/correction`, { signal: controller.signal })
      .then(result => {
        const validated = validateCorrection(result, beatAnalysis);
        if (!controller.signal.aborted) setCorrection({ key: sourceKey, result: validated });
      }).catch(reason => {
        if (!controller.signal.aborted) setCorrectionError({ key: sourceKey, message: reason.message });
      });
    return () => controller.abort();
    // A proposal belongs to a complete analysis snapshot, never a polling render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sourceKey, correctionRetry]);
  const beatKey = beatGrid
    ? `${beatGrid.beats.join(",")}|${beatGrid.downbeats.join(",")}|${beatGrid.time_signature}`
    : "none";
  // Stable sort preserves original order for equal starts without changing saved data.
  const timelineLoops = [...loops].sort((a, b) => a.a - b.a);
  useEffect(() => {
    let mounted = true;
    void loadPractice(track.id).then(saved => {
      if (mounted && !edited.current) setLoops(saved);
    }).catch(() => { if (mounted) setSaveError("Could not load saved loops."); });
    return () => {
      mounted = false;
      if (saveTimer.current) clearTimeout(saveTimer.current);
      if (pending.current) void savePractice(track.id, pending.current).catch(() => {});
    };
  }, [track.id]);
  useEffect(() => { engine.current?.setLoopPlan(loopMode, loops); }, [loopMode, loops]);
  useEffect(() => {
    engine.current?.setClickOptions(beatGrid, countInBars, clickEnabled);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [beatKey, countInBars, clickEnabled]);
  useEffect(() => {
    const preserved = preserveStemMix(mix, stems);
    const next =
      shortcutRef.current.mode === "none"
        ? { mix: preserved, shortcut: shortcutRef.current }
        : retargetPerformanceShortcut(
            preserved,
            stems as EffectiveStem[],
            shortcutRef.current,
            shortcutRef.current.part!,
          );
    shortcutRef.current = next.shortcut;
    setShortcutState(next.shortcut);
    setMix(next.mix);
    // Stem identity, not the array allocated during render, defines the graph.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [graphKey]);
  function updateLoops(next: PracticeLoop[]) {
    edited.current = true;
    setLoops(next);
    pending.current = next;
    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => {
      pending.current = null;
      void savePractice(track.id, next).then(() => setSaveError(""))
        .catch(() => setSaveError("Could not save loops. Edit again to retry."));
    }, 300);
  }
  function editLoop(id: string, changes: Partial<PracticeLoop>) {
    updateLoops(loops.map(loop => loop.id === id ? { ...loop, ...changes } : loop));
  }
  function boundary(field: "a" | "b", value: number) {
    if (!selected) return;
    const next = field === "a" ? Math.max(0, Math.min(value, selected.b - 0.05))
      : Math.min(track.duration, Math.max(value, selected.a + 0.05));
    editLoop(selected.id, { [field]: next });
  }
  function addLoop() {
    if (track.duration < 0.05 || loops.length >= 50) return;
    // Keep the playhead as the start when possible; leave a useful tail at the end.
    const tail = Math.min(track.duration, Math.min(1, Math.max(0.05, track.duration / 4)));
    const a = Math.max(0, Math.min(position, track.duration - tail));
    let number = 1;
    while (loops.some(loop => loop.name === `Loop ${number}`)) number++;
    const loop = { id: crypto.randomUUID(), name: `Loop ${number}`, a,
      b: Math.min(track.duration, a + 8), enabled: true };
    updateLoops([...loops, loop]);
    setSelectedId(loop.id);
  }
  useEffect(() => {
    const player = new MixerEngine();
    engine.current = player;
    // The syncing effect above runs before creation on mount; seed this engine too.
    player.setLoopPlan(loopMode, loops);
    player.setClickOptions(beatGrid, countInBars, clickEnabled);
    player.setClickVolume(clickVolume);
    const recoverAudio = () => {
      player.handleVisibilityChange(document.visibilityState === "hidden");
    };
    document.addEventListener("visibilitychange", recoverAudio);
    const timer = window.setInterval(() => {
      const p = player.position();
      if (player.playing && !player.looping && p >= player.duration)
        player.stop();
      setPosition(p);
      setPlaying(player.playing);
    }, 50);
    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", recoverAudio);
      player.dispose();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => {
    const player = engine.current!;
    const controller = new AbortController();
    const resumeAt = player.position() || positionRef.current;
    setLoaded(false);
    setPlaying(false);
    reloadMixerGraph(
      player,
      stems,
      mixRef.current,
      controller.signal,
      resumeAt,
    )
      .then((restored) => {
        if (restored === null) return;
        setPosition(restored);
        setLoaded(true);
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(e.message);
      });
    return () => controller.abort();
    // Reload only when the effective audio graph changes. Transport and editor
    // state stay mounted, while a new root take still remounts via App's key.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [graphKey]);
  useEffect(() => {
    engine.current?.setMix(effectiveMix);
    try {
      localStorage.setItem(
        `riffroom:mix:${key}`,
        JSON.stringify(restorePerformanceShortcut(mix, shortcut)),
      );
    } catch {
      /* Storage may be disabled. */
    }
  }, [mix, shortcut, key, graphKey]);
  const toggle = useCallback(() => {
    if (!loaded) return;
    const player = engine.current!;
    if (player.playing) player.pause();
    else void player.play(true).catch((e) => setError(e.message));
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
    const next = applyManualChannelChange(
      mix,
      stems as EffectiveStem[],
      shortcutRef.current,
      name,
      values,
    );
    shortcutRef.current = next.shortcut;
    setShortcutState(next.shortcut);
    setMix(next.mix);
  }
  function seek(next: number) {
    engine.current?.seek(next);
    setPosition(next);
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
  const soloed = Object.values(effectiveMix).some((channel) => channel.solo);
  const preferredPartAvailable = isPerformancePartAvailable(
    preferredPart,
    availableParts,
  );
  const playWithBandActive = shortcut.mode === "play-with-band";
  const hearJustActive = shortcut.mode === "hear-just";
  const presetCopy = preferredPart
    ? performancePartCopy(preferredPart)
    : {
        primary: "Play with the band",
        secondary: "Hear just the part",
      };
  const PartIcon = preferredPart
    ? (icons[normalizedStemName(preferredPart)] ?? Music2)
    : Music2;
  function selectPerformancePart(part: string) {
    if (resolved && shortcutRef.current.mode !== "none") {
      const next = retargetPerformanceShortcut(
        mix,
        resolved.stems,
        shortcutRef.current,
        part,
      );
      shortcutRef.current = next.shortcut;
      setShortcutState(next.shortcut);
      setMix(next.mix);
    }
    setPreferredPart(part);
    setPartMenuOpen(false);
    try {
      savePerformancePartPreference(track.id, part, localStorage);
    } catch {
      /* Storage may be disabled. */
    }
  }
  function setPerformanceShortcut(
    mode: Exclude<PerformanceShortcutMode, "none">,
  ) {
    if (!preferredPart || !resolved) return;
    const nextMode = shortcutRef.current.mode === mode ? "none" : mode;
    const next = transitionPerformanceShortcut(
      mix,
      resolved.stems,
      shortcutRef.current,
      nextMode,
      preferredPart,
    );
    shortcutRef.current = next.shortcut;
    setShortcutState(next.shortcut);
    setMix(next.mix);
  }
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
              onClick={() => seek(loopMode ? timelineLoops.find(l => l.enabled)?.a ?? 0 : 0)}
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
            onChange={(e) => seek(+e.target.value)}
          />
          <div
            className="playhead"
            style={{ left: `${(position / track.duration) * 100}%` }}
          />
          {timelineLoops.map((loop, index) => (
            <div key={loop.id} data-testid="loop-region" title={loop.name}
              className={`loop-region ${loop.enabled ? "enabled" : "disabled"} ${loopMode && loop.enabled ? "active" : ""} ${selectedId === loop.id ? "chosen" : ""}`}
              style={{ left: `${loop.a / track.duration * 100}%`, width: `${(loop.b - loop.a) / track.duration * 100}%` }}>
              <span>{index + 1}. {loop.name}</span>
            </div>
          ))}
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
            <button className={`small-button ${loopMode ? "selected" : ""}`}
              onClick={() => setLoopMode(!loopMode)} aria-pressed={loopMode}>
              <Repeat2 size={15} /> Loop
            </button>
            <button className="small-button" onClick={addLoop} disabled={loops.length >= 50 || track.duration < 0.05}>Add loop</button>
            {loopMode && !loops.some(loop => loop.enabled) && <small>Select at least one loop</small>}
          </div>
          <div className="playback-adjustments">
            <div className="click-controls" aria-label="Beat click controls">
              {rawBeatGrid ? <>
                <label className="speed">Count-in{" "}<select value={countInBars}
                  onChange={event => setCountInBars(+event.target.value)}>
                  <option value={0}>Off</option>
                  {[1, 2, 3, 4].map(bars => <option key={bars} value={bars}>
                    {bars} bar{bars === 1 ? "" : "s"}
                  </option>)}
                </select></label>
                <button className={`small-button ${clickEnabled ? "selected" : ""}`}
                  aria-pressed={clickEnabled} onClick={() => setClickEnabled(!clickEnabled)}>Click</button>
                <label className="click-volume">
                  <span>Click level</span>
                  <input aria-label="Click volume" type="range" min="0" max="2"
                    step="0.05" value={clickVolume} onChange={event => {
                      const value = +event.target.value;
                      setClickVolume(value);
                      engine.current?.setClickVolume(value);
                    }} />
                  <span>{Math.round(clickVolume * 100)}%</span>
                </label>
                <button className={`small-button ${correctionEnabled ? "selected" : ""}`}
                  aria-pressed={correctionEnabled}
                  title={correctionDescription}
                  aria-description={correctionDescription}
                  disabled={!correctionEnabled && !currentCorrection && !currentCorrectionError}
                  onClick={() => {
                    const enabled = !correctionEnabled;
                    setCorrectionEnabled(enabled);
                    saveCorrectionPreference(track.id, enabled);
                  }}>Beat correction</button>
                {currentCorrectionError && <button className="small-button"
                  title={correctionDescription} aria-description={correctionDescription}
                  onClick={() => setCorrectionRetry(value => value + 1)}>Retry correction</button>}
              </> : <>
                {(beatAnalysis?.status === "queued" || beatAnalysis?.status === "processing") &&
                  <small role="status">{beatAnalysis.status === "queued" ? "Beats queued…" : "Analyzing beats…"}</small>}
                {beatAnalysis?.status === "error" && <>
                  <small role="status">{beatAnalysis.error || "Beat analysis failed. Retry when ready."}</small>
                  <button className="small-button" disabled={retryingBeats}
                    aria-label="Retry beat analysis" onClick={() => {
                      setBeatRequestError("");
                      setRetryingBeats(true);
                      void api(`/tracks/${track.id}/beats`, { method: "POST" })
                        .catch(reason => setBeatRequestError(reason.message))
                        .finally(() => setRetryingBeats(false));
                    }}>Retry</button>
                </>}
              </>}
              {beatRequestError && <small role="status">{beatRequestError}</small>}
            </div>
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
        <div className="saved-loops">
          {timelineLoops.map((loop, index) => <div className="saved-loop" key={loop.id}>
            <input type="checkbox" aria-label={`Enable ${loop.name}`} checked={loop.enabled}
              onChange={e => editLoop(loop.id, { enabled: e.target.checked })} />
            <button className={`small-button ${selectedId === loop.id ? "selected" : ""}`}
              aria-pressed={selectedId === loop.id} onClick={() => setSelectedId(loop.id)}>
              {index + 1}. {loop.name} <small>{preciseTime(loop.a)} → {preciseTime(loop.b)}</small>
            </button>
            <button className="text-button" aria-label={`Delete ${loop.name}`} onClick={() => {
              if (selectedId === loop.id) setSelectedId(null);
              updateLoops(loops.filter(l => l.id !== loop.id));
            }}>×</button>
          </div>)}
        </div>
        {selected && <div className="loop-editor">
          <label>Name <input key={selected.id} aria-label="Loop name" maxLength={60}
            defaultValue={selected.name} onBlur={e => {
              const name = e.target.value.trim() || selected.name;
              e.target.value = name; editLoop(selected.id, { name });
            }} onKeyDown={e => { if (e.key === "Enter") e.currentTarget.blur(); }} /></label>
          {(["a", "b"] as const).map(field => {
            const label = field === "a" ? "start" : "end";
            return <div className="loop-boundary" key={field}>
              <label>{label === "start" ? "Start" : "End"} <input
                key={`${selected.id}:${selected[field]}`} aria-label={`Loop ${label}`} defaultValue={preciseTime(selected[field])}
                onBlur={e => {
                  const value = parseTime(e.target.value);
                  if (value !== null) boundary(field, value);
                  e.target.value = preciseTime(value === null ? selected[field] : field === "a" ? Math.max(0, Math.min(value, selected.b - 0.05)) : Math.min(track.duration, Math.max(value, selected.a + 0.05)));
                }} onKeyDown={e => { if (e.key === "Enter") e.currentTarget.blur(); }} /></label>
              <button className="small-button" aria-label={`Nudge ${label} back 0.1 seconds`} onClick={() => boundary(field, selected[field] - 0.1)}>−0.1</button>
              <button className="small-button" aria-label={`Nudge ${label} forward 0.1 seconds`} onClick={() => boundary(field, selected[field] + 0.1)}>+0.1</button>
              <button className="small-button" title={`Set loop ${label} at playhead`} onClick={() => boundary(field, position)}>Set {label} at playhead</button>
            </div>;
          })}
        </div>}
        <p className="loop-help">Add passages, select their checkboxes, then turn on Loop to cycle in timeline order. Edit times as seconds or m:ss.mmm.</p>
        {saveError && <small role="alert">{saveError}</small>}
      </section>
      <div className="section-heading">
        <div>
          <h2>{original ? "Original track" : "Stem mixer"}</h2>
          <span>
            {original
              ? "Listen while your stems are being prepared"
              : "Make room for your part"}
          </span>
        </div>
        <button
          className="text-button"
          onClick={() => {
            const nextShortcut = noPerformanceShortcut();
            shortcutRef.current = nextShortcut;
            setShortcutState(nextShortcut);
            setMix((current) => ({ ...current, ...defaults(stems) }));
          }}
        >
          <RotateCcw size={14} /> Reset mix
        </button>
      </div>
      {!original && (
        <div className="presets">
          <div
            className="preset-split"
            onBlur={(event) => {
              if (!event.currentTarget.contains(event.relatedTarget))
                setPartMenuOpen(false);
            }}
          >
            <button
              className={`preset preset-primary ${playWithBandActive ? "selected" : ""}`}
              onClick={() => setPerformanceShortcut("play-with-band")}
              disabled={!preferredPartAvailable}
            >
              <PartIcon size={16} /> {presetCopy.primary}
              {playWithBandActive && <Check size={14} />}
            </button>
            <button
              className="preset preset-menu-toggle"
              aria-label="Choose performance part"
              aria-haspopup="menu"
              aria-expanded={partMenuOpen}
              disabled={!availableParts.length}
              onClick={() => setPartMenuOpen((open) => !open)}
              onKeyDown={(event) => {
                if (event.key === "Escape") setPartMenuOpen(false);
              }}
            >
              <ChevronDown size={14} />
            </button>
            {partMenuOpen && (
              <div className="preset-menu" role="menu">
                {availableParts.map((part) => {
                  const ChoiceIcon = icons[normalizedStemName(part)] ?? Music2;
                  return (
                    <button
                      key={part}
                      type="button"
                      role="menuitemradio"
                      aria-checked={part === preferredPart}
                      onClick={() => selectPerformancePart(part)}
                    >
                      <ChoiceIcon size={14} />
                      <span>{partLabel(part)}</span>
                      {part === preferredPart && <Check size={13} />}
                    </button>
                  );
                })}
              </div>
            )}
          </div>
          <button
            className={`preset ${hearJustActive ? "selected" : ""}`}
            disabled={!preferredPartAvailable}
            onClick={() => setPerformanceShortcut("hear-just")}
          >
            <Headphones size={16} /> {presetCopy.secondary}
            {hearJustActive && <Check size={14} />}
          </button>
        </div>
      )}
      <div className="stem-list">
        {resolved?.expansions.map((point) => (
          <div
            className="stem-expansion"
            key={`${point.parentRunId}:${point.parentStemName}`}
          >
            <div>
              <Split size={14} />
              <span>
                <strong>{point.context}</strong> is split further
              </span>
            </div>
            <select
              aria-label={`Split used for ${point.context}`}
              value={point.activeChildId ?? "parent"}
              disabled={busy}
              onChange={(event) =>
                onSelectExpansion?.(
                  point.parentRunId,
                  point.parentStemName,
                  event.target.value === "parent" ? null : event.target.value,
                )
              }
            >
              <option value="parent">Use unsplit {point.parentStemName}</option>
              {point.children.map((child) => (
                <option value={child.id} key={child.id}>
                  {modelCatalog.find((model) => model.id === child.model_id)
                    ?.name ?? child.model_id}
                  {` · split ${child.split_number ?? "?"}`}
                </option>
              ))}
            </select>
            {point.activeChildId && (
              <button
                className="icon-button"
                aria-label={`Delete selected split for ${point.context}`}
                disabled={busy}
                onClick={() => onDeleteRun?.(point.activeChildId!)}
              >
                <Trash2 size={14} />
              </button>
            )}
          </div>
        ))}
        {stems.map((stem) => {
          const c = effectiveMix[stem.name],
            effective = stem as EffectiveStem,
            displayName = effective.displayName ?? stem.name,
            Icon = icons[displayName] ?? Music2,
            color = colors[displayName] ?? "#aebec9",
            splitKey = `${effective.sourceRunId}:${effective.sourceStemName}`,
            splitModel = splitModels[splitKey] ?? models[0]?.id ?? "";
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
                <strong>{displayName}</strong>
                <span>
                  {effective.depth ? `${effective.context} · ` : ""}
                  {c.solo ? "Solo" : silent ? "Muted" : "Stereo"}
                </span>
              </div>
              <div className="stem-wave">
                <Waveform
                  peaks={stem.peaks}
                  color={color}
                  progress={position / track.duration}
                />
                <input
                  aria-label={`Seek ${effective.context}`}
                  type="range"
                  min="0"
                  max={track.duration}
                  step="0.05"
                  value={position}
                  onChange={(e) => seek(+e.target.value)}
                />
              </div>
              <div className="stem-actions">
                <button
                  className={
                    c.muted ? "channel-button muted" : "channel-button"
                  }
                  aria-label={`Mute ${effective.context}`}
                  aria-pressed={c.muted}
                  onClick={() => change(stem.name, { muted: !c.muted })}
                >
                  M
                </button>
                <button
                  className={c.solo ? "channel-button solo" : "channel-button"}
                  aria-label={`Solo ${effective.context}`}
                  aria-pressed={c.solo}
                  onClick={() => change(stem.name, { solo: !c.solo })}
                >
                  S
                </button>
              </div>
              {!original && (
                <div className="stem-split-action">
                  <select
                    aria-label={`Model to split ${effective.context}`}
                    value={splitModel}
                    disabled={busy || !models.length}
                    onChange={(event) =>
                      setSplitModels((current) => ({
                        ...current,
                        [splitKey]: event.target.value,
                      }))
                    }
                  >
                    {models.map((model) => (
                      <option key={model.id} value={model.id}>
                        {model.name}
                      </option>
                    ))}
                  </select>
                  <button
                    className="small-button"
                    disabled={busy || !splitModel}
                    onClick={() =>
                      onSeparateStem?.(
                        effective.sourceRunId,
                        effective.sourceStemName,
                        splitModel,
                      )
                    }
                  >
                    <Split size={13} /> Split further
                  </button>
                </div>
              )}
              <div className="stem-volume">
                <input
                  aria-label={`${effective.context} volume`}
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
                download={`${track.title}-${displayName}.wav`}
                title={`Download ${displayName}`}
                aria-label={`Download ${displayName}`}
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
