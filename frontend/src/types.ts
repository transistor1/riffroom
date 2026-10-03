export type Stem = { name: string; file: string; url: string; peaks: number[] };
export type Run = {
  id: string;
  model_id: string;
  provider_id?: string;
  stems: Stem[];
};
export type PracticeLoop = { id: string; name: string; a: number; b: number; enabled: boolean };
export type PracticeConfig = { loops: PracticeLoop[] };
export type Track = {
  practice?: PracticeConfig;
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
  filename: string;
  stems: string[];
  description: string;
  badge: string;
  license: string;
  source: string;
  provider: string | null;
  provider_options: string[];
  architecture: string;
  supported_platforms: string[];
  terms_status: "open" | "non-commercial" | "unverified";
  curated: boolean;
  catalog_origin: string;
  catalog_group: "curated" | "community";
  prepared: boolean;
  cache_bytes: number;
  cache_label: "Prepared" | "Downloads on first use";
  cache_cleanup_supported: boolean;
  compatibility: {
    platform_key: string;
    platform_name: string;
    platform_supported: boolean;
    runtime_available: boolean;
    compatible: boolean;
    label: string;
  };
};
export type RuntimeStatus = {
  id: "audio-separator";
  display_name: string;
  version: string;
  available: boolean;
  managed_installed: boolean;
  installing: boolean;
  error: string | null;
};
export type Channel = { volume: number; muted: boolean; solo: boolean };
export type Mix = Record<string, Channel>;
export const active = (track?: Track | null) =>
  !!track && ["queued", "processing"].includes(track.status);
export const time = (seconds: number) =>
  `${Math.floor(Math.max(0, seconds) / 60)}:${String(Math.floor(Math.max(0, seconds) % 60)).padStart(2, "0")}`;

export function preciseTime(seconds: number): string {
  const ms = Math.round(Math.max(0, seconds) * 1000);
  return `${Math.floor(ms / 60000)}:${(Math.floor(ms / 1000) % 60).toString().padStart(2, "0")}.${(ms % 1000).toString().padStart(3, "0")}`;
}
export function parseTime(text: string): number | null {
  const value = text.trim();
  if (!/^(?:\d+:)?\d+(?:\.\d+)?$/.test(value)) return null;
  const parts = value.split(":").map(Number);
  if (parts.length === 2 && parts[1] >= 60) return null;
  const result = parts.length === 2 ? parts[0] * 60 + parts[1] : parts[0];
  return Number.isFinite(result) ? result : null;
}
