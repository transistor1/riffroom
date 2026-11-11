import { useEffect, useRef, useState } from "react";
import { Pencil } from "lucide-react";
import { api } from "../api";
import type { Track } from "../types";

// Mount by track ID, so polling can update props without replacing the draft.
export default function TrackTitle({
  track,
  onRenamed,
}: {
  track: Track;
  onRenamed: (id: string, title: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const editButton = useRef<HTMLButtonElement>(null);
  const inFlight = useRef(false);

  useEffect(() => {
    if (editing) {
      input.current?.focus();
      input.current?.select();
    }
  }, [editing]);

  function finish() {
    setEditing(false);
    setError("");
    // Wait for the Edit button to return to the DOM.
    requestAnimationFrame(() => editButton.current?.focus());
  }

  async function save() {
    if (inFlight.current) return;
    const title = draft.trim();
    if (!title || Array.from(title).length > 200) {
      setError("Enter a title between 1 and 200 characters.");
      input.current?.focus();
      return;
    }
    inFlight.current = true;
    setSaving(true);
    setError("");
    try {
      const saved = await api<Track>(`/tracks/${track.id}/title`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title }),
      });
      onRenamed(track.id, saved.title);
      finish();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Could not save title.");
    } finally {
      inFlight.current = false;
      setSaving(false);
    }
  }

  if (!editing) {
    return (
      <div className="track-title-row">
        <h1>{track.title}</h1>
        <button
          ref={editButton}
          className="text-button edit-title"
          onClick={() => {
            setDraft(track.title);
            setError("");
            setEditing(true);
          }}
        >
          <Pencil size={14} aria-hidden="true" /> Edit title
        </button>
      </div>
    );
  }

  return (
    <form
      className="track-title-editor"
      aria-label="Edit track title"
      aria-busy={saving}
      onSubmit={(event) => {
        event.preventDefault();
        void save();
      }}
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          event.preventDefault();
          if (!inFlight.current) finish();
        }
      }}
    >
      <label className="visually-hidden" htmlFor="track-title-input">Song title</label>
      <input
        id="track-title-input"
        ref={input}
        value={draft}
        readOnly={saving}
        aria-invalid={Boolean(error)}
        aria-describedby={error ? "track-title-error" : undefined}
        onChange={(event) => {
          setDraft(event.target.value);
          setError("");
        }}
      />
      <button className="small-button" type="submit" disabled={saving}>
        {saving ? "Saving…" : "Save title"}
      </button>
      <button className="text-button" type="button" disabled={saving} onClick={finish}>
        Cancel
      </button>
      {error && <div id="track-title-error" className="title-error" role="alert">{error}</div>}
    </form>
  );
}
