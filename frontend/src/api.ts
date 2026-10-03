export async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, options);
  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ detail: "The server could not complete this request." }));
    throw new Error(
      typeof error.detail === "string"
        ? error.detail
        : "Please check your input and try again.",
    );
  }
  return response.status === 204 ? (undefined as T) : response.json();
}

// Serialize writes across Mixer remounts so older edits cannot overwrite newer ones.
import type { PracticeLoop, Track } from "./types";
const practiceWrites = new Map<string, Promise<unknown>>();
export function savePractice(id: string, loops: PracticeLoop[]): Promise<Track> {
  const previous = practiceWrites.get(id) ?? Promise.resolve();
  const next = previous.catch(() => {}).then(() => api<Track>(`/tracks/${id}/practice`, {
    method: "PUT", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ loops }), keepalive: true,
  }));
  practiceWrites.set(id, next);
  void next.finally(() => {
    if (practiceWrites.get(id) === next) practiceWrites.delete(id);
  }).catch(() => {});
  return next;
}
export async function loadPractice(id: string): Promise<PracticeLoop[]> {
  await practiceWrites.get(id)?.catch(() => {});
  return (await api<Track>(`/tracks/${id}`)).practice?.loops ?? [];
}
