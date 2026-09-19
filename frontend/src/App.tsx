import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  AudioLines,
  Boxes,
  ChevronRight,
  CircleHelp,
  FolderOpen,
  Guitar,
  Headphones,
  Layers,
  LoaderCircle,
  Music2,
  Plus,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import { api } from "./api";
import { active, time, type Model, type Track } from "./types";
import Mixer from "./components/Mixer";

const json = (value: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(value),
});

type DeleteTarget =
  | { kind: "track"; trackId: string }
  | { kind: "run"; trackId: string; runId: string }
  | { kind: "model-cache"; modelId: string; modelName: string };

type OpenModal = "help" | "models" | null;

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let value = bytes / 1024;
  let unit = units[0];
  for (const next of units.slice(1)) {
    if (value < 1024) break;
    value /= 1024;
    unit = next;
  }
  return `${value >= 10 ? value.toFixed(0) : value.toFixed(1)} ${unit}`;
}

export default function App() {
  const [models, setModels] = useState<Model[]>([]);
  const [tracks, setTracks] = useState<Track[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [modelId, setModelId] = useState("demucs-6");
  const [runId, setRunId] = useState<string | null>(null);
  const [importOpen, setImportOpen] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState("");
  const [openModal, setOpenModal] = useState<OpenModal>(null);
  const [loading, setLoading] = useState(true);
  const [deleteTarget, setDeleteTarget] = useState<DeleteTarget | null>(null);
  const [modelError, setModelError] = useState("");
  const [removingModelId, setRemovingModelId] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const track = tracks.find((t) => t.id === selectedId);
  const run = track?.runs.find((r) => r.id === (runId ?? track.active_run));
  const model = models.find((m) => m.id === modelId);
  const refreshModels = useCallback(async () => {
    setModels(await api<Model[]>("/models"));
  }, []);
  const refresh = useCallback(async () => {
    try {
      const data = await api<Track[]>("/tracks");
      setTracks(data);
      setError((current) =>
        current.startsWith("Cannot connect") ? "" : current,
      );
    } catch {
      setError(
        "Cannot connect to Riffroom. Make sure the local server is running.",
      );
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    void refreshModels().catch((e) => setError(e.message));
    void refresh();
    const timer = setInterval(refresh, 2000);
    return () => clearInterval(timer);
  }, [refresh, refreshModels]);
  useEffect(() => {
    if (!openModal && !deleteTarget) return;
    const previous = document.activeElement as HTMLElement | null;
    const dialog = document.querySelector<HTMLElement>('[role="dialog"]');
    const controls = () =>
      Array.from(
        dialog?.querySelectorAll<HTMLElement>(
          'button, a[href], input, select, [tabindex="0"]',
        ) ?? [],
      );
    controls()[0]?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpenModal(null);
        setDeleteTarget(null);
      }
      if (event.key === "Tab") {
        const items = controls(),
          first = items[0],
          last = items.at(-1);
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last?.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first?.focus();
        }
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      previous?.focus();
    };
  }, [openModal, deleteTarget]);
  function selectTrack(t: Track) {
    setSelectedId(t.id);
    setRunId(null);
    setImportOpen(false);
    setModelId(t.runs.at(-1)?.model_id ?? t.pending_model ?? "demucs-6");
  }
  async function upload(file?: File) {
    if (!file || uploading) return;
    if (file.size > 512 * 1024 * 1024) {
      setError("Choose a track smaller than 512 MB.");
      return;
    }
    setUploading(true);
    setError("");
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("model_id", modelId);
      const added = await api<Track>("/tracks", { method: "POST", body: form });
      setTracks((current) => [added, ...current]);
      selectTrack(added);
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setUploading(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  }
  async function action(fn: () => Promise<unknown>) {
    try {
      setError("");
      await fn();
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    }
  }
  async function removeModelCache(
    target: Extract<DeleteTarget, { kind: "model-cache" }>,
  ) {
    setRemovingModelId(target.modelId);
    setModelError("");
    try {
      await api(`/models/${target.modelId}/cache`, { method: "DELETE" });
      await refreshModels();
    } catch (e) {
      setModelError((e as Error).message);
    } finally {
      setRemovingModelId(null);
      setDeleteTarget(null);
    }
  }
  const showImport = importOpen || !track;
  return (
    <div
      className="app-shell"
      onDragOver={(e) => {
        e.preventDefault();
        if (e.dataTransfer.types.includes("Files")) setDragging(true);
      }}
      onDrop={(e) => {
        e.preventDefault();
        setDragging(false);
        void upload(e.dataTransfer.files[0]);
      }}
    >
      <aside className="sidebar">
        <a
          className="brand"
          href="#"
          onClick={(e) => {
            e.preventDefault();
            setSelectedId(null);
            setImportOpen(false);
          }}
        >
          <span className="brand-mark">
            <AudioLines size={25} />
          </span>
          <span>
            riffroom<span className="brand-dot">.</span>
          </span>
        </a>
        <div className="workspace-label">YOUR PRACTICE SPACE</div>
        <button className="new-track" onClick={() => setImportOpen(true)}>
          <Plus size={18} /> Import a track
        </button>
        <div className="library-title">
          <span>Library</span>
          <span>{tracks.length}</span>
        </div>
        <nav className="library" aria-label="Track library">
          {tracks.map((t) => (
            <button
              key={t.id}
              className={`library-track ${t.id === selectedId && !importOpen ? "current" : ""}`}
              onClick={() => selectTrack(t)}
            >
              <span className="library-icon">
                {active(t) ? (
                  <LoaderCircle size={17} className="spin" />
                ) : (
                  <Music2 size={17} />
                )}
              </span>
              <span>
                <strong>{t.title}</strong>
                <small>
                  {active(t)
                    ? "Separating…"
                    : t.status === "error"
                      ? "Needs attention"
                      : `${time(t.duration)} · ${t.runs.length ? `${t.runs.at(-1)!.stems.length} stems` : "Original"}`}
                </small>
              </span>
              {t.id === selectedId && <span className="library-dot" />}
            </button>
          ))}
          {!tracks.length && (
            <p className="empty-library">
              Your songs will live here.
              <br />
              Ready whenever you are.
            </p>
          )}
        </nav>
        <div className="sidebar-bottom">
          <button
            onClick={() => {
              setModelError("");
              setOpenModal("models");
              void refreshModels().catch((e) => setModelError(e.message));
            }}
          >
            <Boxes size={16} /> Model manager
          </button>
          <button onClick={() => setOpenModal("help")}>
            <CircleHelp size={16} /> A little help
          </button>
          <div className="local-status">
            <span /> Local on your Mac <span className="version">v0.1</span>
          </div>
        </div>
      </aside>
      <main>
        <header className="topbar">
          <div>
            <span>Practice room</span>
            <ChevronRight size={13} />
            <strong>{showImport ? "New session" : track.title}</strong>
          </div>
          <span className="private-badge">
            <span /> ALL YOURS. ALL LOCAL.
          </span>
        </header>
        <div className="main-content">
          {error && (
            <div className="error" role="alert">
              {error}
              <button aria-label="Dismiss error" onClick={() => setError("")}>
                <X size={15} />
              </button>
            </div>
          )}
          {showImport ? (
            <>
              <div className="intro-label">
                <span /> LESS FIDDLING. MORE PLAYING.
              </div>
              <h1>
                Your song.
                <br />
                Your part. <em>Your room.</em>
              </h1>
              <p className="intro-copy">
                Turn your favorite tracks into your own backing band.
                <br />
                Drop in a song, find your mix, and plug in.
              </p>
              <section className="import-card" aria-label="Import track">
                <div className="import-art">
                  <AudioLines size={34} strokeWidth={1.3} />
                </div>
                <h2>
                  {uploading
                    ? "Getting your track ready…"
                    : "Bring a song to the room"}
                </h2>
                <p>Drag an audio file anywhere, or choose one below.</p>
                <button
                  className="primary-button"
                  disabled={uploading || loading}
                  onClick={() => fileInput.current?.click()}
                >
                  {uploading ? (
                    <LoaderCircle size={17} className="spin" />
                  ) : (
                    <FolderOpen size={17} />
                  )}
                  {uploading ? "Importing…" : "Choose a track"}
                </button>
                <span className="file-formats">
                  MP3, WAV, FLAC, M4A, AIFF & more · up to 20 min / 512 MB
                </span>
              </section>
              <section className="model-selection">
                <div className="section-heading">
                  <div>
                    <h2>Choose your separation model</h2>
                    <span>
                      You can try another model on the same track later.
                    </span>
                  </div>
                  <Layers size={19} />
                </div>
                <div className="model-cards">
                  {models.map((m) => (
                    <button
                      className={`model-card ${modelId === m.id ? "chosen" : ""}`}
                      key={m.id}
                      onClick={() => setModelId(m.id)}
                    >
                      <div>
                        <span className="model-badge">{m.badge}</span>
                        <span className="radio-dot">
                          {modelId === m.id && <span />}
                        </span>
                      </div>
                      <h3>{m.name}</h3>
                      <p>{m.description}</p>
                      <span className="model-stems">
                        {m.stems.length} stems · {m.compatibility.label}
                      </span>
                    </button>
                  ))}
                </div>
              </section>
              <div className="welcome-footer">
                <Headphones size={17} />
                <p>
                  No subscriptions. No uploads to the cloud.
                  <br />
                  <span>
                    Models download once. Your music stays right here.
                  </span>
                </p>
              </div>
            </>
          ) : (
            <>
              <div className="track-heading">
                <div>
                  <div className="eyebrow">NOW IN THE ROOM</div>
                  <h1>{track.title}</h1>
                  <p>
                    {time(track.duration)} <span>·</span>{" "}
                    {run
                      ? models.find((m) => m.id === run.model_id)?.name
                      : "Original audio"}{" "}
                    <span>·</span> Stereo
                  </p>
                </div>
                <button
                  className="icon-button delete-track"
                  aria-label="Delete track"
                  title="Delete track"
                  onClick={() =>
                    setDeleteTarget({ kind: "track", trackId: track.id })
                  }
                >
                  <Trash2 size={17} />
                </button>
              </div>
              {active(track) && (
                <div className="job-status" role="status">
                  <LoaderCircle size={22} className="spin" />
                  <div>
                    <strong>
                      {track.status === "queued"
                        ? "Your track is in the queue"
                        : "Finding the instruments in your song"}
                    </strong>
                    <span>{track.message}</span>
                    <small>
                      First use may take longer while model weights download.
                      You can leave this page open.
                    </small>
                  </div>
                  <button
                    className="text-button"
                    onClick={() =>
                      void action(() =>
                        api(`/tracks/${track.id}/cancel`, { method: "POST" }),
                      )
                    }
                  >
                    Cancel
                  </button>
                </div>
              )}
              {track.error && (
                <div className="error">
                  <div>
                    <strong>Separation needs another try</strong>
                    <p>{track.error}</p>
                    <a
                      href={`/api/tracks/${track.id}/log`}
                      target="_blank"
                      rel="noreferrer"
                    >
                      Open diagnostic log
                    </a>
                  </div>
                </div>
              )}
              {track.runs.length > 0 && (
                <div className="run-select">
                  <div className="run-picker">
                    <label>
                      Listening to{" "}
                      <select
                        aria-label="Separation result"
                        value={runId ?? track.active_run ?? "original"}
                        onChange={(e) => setRunId(e.target.value)}
                      >
                        <option value="original">Original mix</option>
                        {track.runs.map((r, i) => (
                          <option key={r.id} value={r.id}>
                            {models.find((m) => m.id === r.model_id)?.name ??
                              r.model_id}{" "}
                            · take {i + 1}
                          </option>
                        ))}
                      </select>
                    </label>
                    {run && (
                      <button
                        className="icon-button delete-run"
                        aria-label="Delete separation result"
                        title="Delete separation result"
                        disabled={active(track)}
                        onClick={() =>
                          setDeleteTarget({
                            kind: "run",
                            trackId: track.id,
                            runId: run.id,
                          })
                        }
                      >
                        <Trash2 size={15} />
                      </button>
                    )}
                  </div>
                  <span>Mix settings save automatically</span>
                </div>
              )}
              <Mixer
                key={`${track.id}:${run?.id ?? "original"}`}
                track={track}
                run={run}
              />
              <section className="model-footer panel">
                <div className="model-footer-heading">
                  <Layers size={19} />
                  <div>
                    <h3>Find the right separation</h3>
                    <p>
                      Try another model. Previous results stay in the listening
                      menu.
                    </p>
                  </div>
                </div>
                <div className="model-footer-actions">
                  <select
                    aria-label="Separation model"
                    value={modelId}
                    onChange={(e) => setModelId(e.target.value)}
                  >
                    {models.map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.name}
                      </option>
                    ))}
                  </select>
                  <button
                    className="small-button"
                    disabled={active(track)}
                    onClick={() =>
                      void action(() =>
                        api(
                          `/tracks/${track.id}/separate`,
                          json({ model_id: modelId }),
                        ),
                      )
                    }
                  >
                    {active(track) ? "Working…" : "Separate track"}
                  </button>
                </div>
                <p className="model-detail">{model?.description}</p>
              </section>
              <div className="guitar-note">
                <Guitar size={16} />
                <span>
                  Guitar stems contain lead and rhythm together. Separating
                  those reliably is still an open challenge for the local models
                  included here.
                </span>
              </div>
            </>
          )}
        </div>
        <footer className="page-footer">
          <span>Made for the part you want to play.</span>
          <AudioLines size={18} />
        </footer>
      </main>
      <input
        className="visually-hidden"
        ref={fileInput}
        type="file"
        accept="audio/*,.mp3,.wav,.flac,.m4a,.aiff,.aif,.ogg,.opus,.wma"
        onChange={(e) => void upload(e.target.files?.[0])}
      />
      {dragging && (
        <div className="drop-overlay" onDragLeave={() => setDragging(false)}>
          <Upload size={48} />
          <h2>Drop it in. Make it yours.</h2>
          <p>Separate with {model?.name}</p>
        </div>
      )}
      {openModal === "models" && deleteTarget?.kind !== "model-cache" && (
        <div className="modal-backdrop" onClick={() => setOpenModal(null)}>
          <section
            className="modal model-manager"
            role="dialog"
            aria-modal="true"
            aria-labelledby="model-manager-title"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              className="modal-close icon-button"
              aria-label="Close model manager"
              onClick={() => setOpenModal(null)}
            >
              <X size={20} />
            </button>
            <Boxes className="accent" size={29} />
            <h2 id="model-manager-title">Model manager</h2>
            <p>
              Browse Riffroom&apos;s curated separation models and the terms
              attached to their checkpoint weights.
            </p>
            <p className="model-download-note">
              Prepared files stay in Riffroom&apos;s local model cache. Removing
              them means the model will prepare again on next use.
            </p>
            {modelError && (
              <div className="manager-error" role="alert">
                {modelError}
                <button
                  aria-label="Dismiss model error"
                  onClick={() => setModelError("")}
                >
                  <X size={14} />
                </button>
              </div>
            )}
            <div className="manager-models">
              {models.map((m) => (
                <article className="manager-model" key={m.id}>
                  <header>
                    <div>
                      <h3>{m.name}</h3>
                      <span className="model-badge">{m.badge}</span>
                    </div>
                    <span
                      className={`compatibility ${m.compatibility.compatible ? "compatible" : "unavailable"}`}
                    >
                      {m.compatibility.label}
                    </span>
                  </header>
                  <dl>
                    <div>
                      <dt>Architecture</dt>
                      <dd>{m.architecture}</dd>
                    </div>
                    <div>
                      <dt>Provider / runtime</dt>
                      <dd>
                        <code>{m.provider}</code>
                      </dd>
                    </div>
                    <div>
                      <dt>Output stems</dt>
                      <dd className="stem-list">{m.stems.join(", ")}</dd>
                    </div>
                    <div>
                      <dt>Prepared files</dt>
                      <dd className="cache-detail">
                        <span className={m.prepared ? "prepared" : ""}>
                          {m.cache_label}
                        </span>
                        {m.cache_bytes > 0 && (
                          <span>{formatBytes(m.cache_bytes)}</span>
                        )}
                      </dd>
                    </div>
                  </dl>
                  <div className="model-terms">
                    <span className={`terms-status ${m.terms_status}`}>
                      {m.terms_status === "non-commercial"
                        ? "Non-commercial terms"
                        : m.terms_status === "unverified"
                          ? "Unverified terms"
                          : "Open terms"}
                    </span>
                    <p>{m.license}</p>
                  </div>
                  <div className="manager-model-actions">
                    <a href={m.source} target="_blank" rel="noreferrer">
                      Source for {m.name}
                    </a>
                    <div>
                      {m.prepared && m.cache_cleanup_supported && (
                        <button
                          className="remove-cache-button"
                          onClick={() =>
                            setDeleteTarget({
                              kind: "model-cache",
                              modelId: m.id,
                              modelName: m.name,
                            })
                          }
                        >
                          Remove prepared files
                        </button>
                      )}
                      {m.compatibility.compatible && (
                        <button
                          className="small-button"
                          aria-pressed={modelId === m.id}
                          onClick={() => {
                            setModelId(m.id);
                            setOpenModal(null);
                          }}
                        >
                          {modelId === m.id ? "Using model" : "Use model"}
                        </button>
                      )}
                    </div>
                  </div>
                </article>
              ))}
            </div>
          </section>
        </div>
      )}
      {openModal === "help" && (
        <div className="modal-backdrop" onClick={() => setOpenModal(null)}>
          <section
            className="modal"
            role="dialog"
            aria-modal="true"
            aria-label="Riffroom help"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              className="modal-close icon-button"
              aria-label="Close help"
              onClick={() => setOpenModal(null)}
            >
              <X size={20} />
            </button>
            <Headphones className="accent" size={29} />
            <h2>A little help, then back to playing.</h2>
            <p>
              Import a song and let a model split it into instruments.
              Separation runs locally; first use needs internet to download
              model weights.
            </p>
            <ul>
              <li>
                <b>M</b> mutes a stem. <b>S</b> solos it. You can solo more than
                one.
              </li>
              <li>
                Set volume from 0–200%. The master controls the whole mix.
              </li>
              <li>
                Seek to a section, click <b>A</b> for its start and <b>B</b> for
                its end, then turn on Loop.
              </li>
              <li>
                <b>Space</b> plays or pauses. Arrow keys skip five seconds.
              </li>
              <li>
                Change speed without changing tuning, or use Pitch to transpose
                playback by up to one octave.
              </li>
              <li>
                Download any stem with its arrow button. Original audio and all
                model results stay in your library until deleted.
              </li>
            </ul>
            <p className="muted-copy">
              Local data lives in the project's data folder. Keep the Riffroom
              server running while separating and playing.
            </p>
            <button
              className="primary-button"
              onClick={() => setOpenModal(null)}
            >
              Back to the room <ArrowLeft size={15} />
            </button>
          </section>
        </div>
      )}
      {deleteTarget && (
        <div className="modal-backdrop">
          <section
            className="modal compact"
            role="dialog"
            aria-modal="true"
            aria-label={
              deleteTarget.kind === "model-cache"
                ? "Remove prepared model files confirmation"
                : deleteTarget.kind === "run"
                  ? "Delete separation result confirmation"
                  : "Delete track confirmation"
            }
          >
            <h2>
              {deleteTarget.kind === "model-cache"
                ? `Remove prepared files for ${deleteTarget.modelName}?`
                : deleteTarget.kind === "run"
                  ? "Remove this separation result?"
                  : "Remove this track?"}
            </h2>
            {deleteTarget.kind === "model-cache" ? (
              <p>
                This removes only this model&apos;s prepared files. Tracks and
                separation results stay in your library. The model will prepare
                again on next use.
              </p>
            ) : deleteTarget.kind === "run" ? (
              <p>
                This removes only this generated set of stems. Your original
                audio and other separation results will remain.
              </p>
            ) : (
              <p>
                This deletes the imported copy and its separated stems from
                Riffroom. Your original file is untouched.
              </p>
            )}
            <div className="dialog-actions">
              <button
                className="small-button"
                disabled={
                  deleteTarget.kind === "model-cache" &&
                  removingModelId === deleteTarget.modelId
                }
                onClick={() => setDeleteTarget(null)}
              >
                {deleteTarget.kind === "model-cache"
                  ? "Keep prepared files"
                  : deleteTarget.kind === "run"
                    ? "Keep result"
                    : "Keep track"}
              </button>
              <button
                className="danger-button"
                disabled={
                  (deleteTarget.kind === "model-cache" &&
                    removingModelId === deleteTarget.modelId) ||
                  (deleteTarget.kind === "run" &&
                    active(
                      tracks.find((item) => item.id === deleteTarget.trackId),
                    ))
                }
                onClick={() => {
                  const target = deleteTarget;
                  if (target.kind === "model-cache") {
                    void removeModelCache(target);
                    return;
                  }
                  setDeleteTarget(null);
                  void action(async () => {
                    if (target.kind === "track") {
                      await api(`/tracks/${target.trackId}`, {
                        method: "DELETE",
                      });
                      if (selectedId === target.trackId) setSelectedId(null);
                      return;
                    }
                    await api(
                      `/tracks/${target.trackId}/runs/${target.runId}`,
                      { method: "DELETE" },
                    );
                    try {
                      localStorage.removeItem(
                        `riffroom:mix:${target.trackId}:${target.runId}`,
                      );
                    } catch {
                      /* Storage may be disabled. */
                    }
                    if (selectedId === target.trackId) setRunId(null);
                  });
                }}
              >
                {deleteTarget.kind === "model-cache"
                  ? removingModelId === deleteTarget.modelId
                    ? "Removing…"
                    : "Remove prepared files"
                  : deleteTarget.kind === "run"
                    ? "Remove result"
                    : "Remove track"}
              </button>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
