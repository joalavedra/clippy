export type Platform = "youtube" | "tiktok" | "instagram" | "gdrive" | "local";
export type Layout = "single" | "podcast";
export type Ratio = "9:16" | "16:9" | "1:1";
export type AssetState = "not_planned" | "planned" | "ready" | "posted";

export interface Project {
  id: string;
  name: string;
  platform: Platform;
  url: string | null;
  local_path: string | null;
  layout: Layout;
  created_at: string;
}

export interface Render {
  id: string;
  asset_id: string;
  ratio: Ratio | string;
  duration: number;
  file_key: string;
  thumb_key: string | null;
  url: string;
  thumb_url: string | null;
  recipe_clip: Record<string, unknown>;
}

export interface AssetMetadata {
  metadata?: {
    title?: string;
    description?: string;
    hashtags?: string[];
  };
  [key: string]: unknown;
}

export interface Asset {
  id: string;
  job_id: string;
  project_ids: string[];
  clip_id: number;
  title: string;
  hook_line: string;
  rationale: string;
  viral_score: number;
  hashtags: string[];
  metadata: AssetMetadata;
  state: AssetState;
  favorite: boolean;
  created_at: string;
  renders: Render[];
}

export interface JobFormat {
  ratio: Ratio;
  min: number;
  max: number;
  variants?: Ratio[];
}

export interface JobOptions {
  whisper_model: string;
  whisper_device: string;
  whisper_compute_type: string;
  story_style: "styled";
  gemini_timeout: number;
  project_name: string | null;
}

export interface Job {
  id: string;
  brief: string;
  formats: JobFormat[];
  clips: number;
  options: JobOptions;
  project_ids: string[];
  status: "queued" | "running" | "done" | "failed";
  stage: string;
  percent: number;
  error: string | null;
  created_at: string;
  updated_at: string;
}

export interface JobEvent {
  id: string;
  job_id: string;
  ts: string;
  stage: string;
  message: string;
}

export interface Health {
  status: string;
  worker_alive: boolean;
  queued: number;
  running: number;
}

export interface SearchResult {
  window_id: string;
  project_id: string;
  project_name: string;
  start: number;
  end: number;
  text: string;
  highlight: string;
  score: number;
  lexical: number;
  semantic: number;
}

export interface SearchResponse {
  query: string;
  mode: "hybrid" | "lexical";
  took_ms: number;
  indexed_windows: number;
  results: SearchResult[];
}
