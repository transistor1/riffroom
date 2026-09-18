export type Stem = { name: string; file: string; url: string; peaks: number[] };
export type Run = { id: string; model_id: string; stems: Stem[] };
export type Track = {
  id: string;
  title: string;
  filename: string;
  duration: number;
  created_at: string;
  status: "idle" | "queued" | "processing" | "ready" | "error";
  message: string;
  runs: Run[];
  active_run: string | null;
  peaks: number[];
  error: string | null;
  pending_model?: string;
};
export type Model = {
  id: string;
  name: string;
  stems: string[];
  description: string;
  badge: string;
  license: string;
  source: string;
};
export type Channel = { volume: number; muted: boolean; solo: boolean };
export type Mix = Record<string, Channel>;
export const active = (track?: Track | null) =>
  !!track && ["queued", "processing"].includes(track.status);
export const time = (seconds: number) =>
  `${Math.floor(Math.max(0, seconds) / 60)}:${String(Math.floor(Math.max(0, seconds) % 60)).padStart(2, "0")}`;
