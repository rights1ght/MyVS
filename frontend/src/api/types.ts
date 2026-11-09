export type Severity = "warning" | "high" | "critical";

export interface GpuInfo {
  available: boolean;
  name: string;
  error: string;
  util: number | null;
  vram_used_mb: number | null;
  vram_total_mb: number | null;
  temp_c: number | null;
  power_w: number | null;
  clock_mhz: number | null;
}

export interface CpuInfo {
  percent: number;
  per_core: number[];
  freq_mhz: number | null;
  temp_c: number | null;
}

export interface RamInfo {
  used_mb: number;
  total_mb: number;
  available_mb: number;
  percent: number;
  swap_used_mb: number;
  swap_total_mb: number;
  swap_percent: number;
}

export interface DiskInfo {
  read_mb_s: number;
  write_mb_s: number;
  free_gb: number;
  total_gb: number;
}

export interface AlertInfo {
  id: string;
  ts: string;
  severity: Severity;
  metric: string;
  value: number;
  threshold: number;
  model_id: string;
  task_id: string;
  message: string;
  acknowledged: boolean;
}

export interface LoadedModelInfo {
  model_id: string;
  model_name?: string;
  state: string;
  device: string;
  precision?: string;
  vram_mb?: number;
  ram_mb?: number;
  last_used?: string | null;
  task_id?: string | null;
}

export interface Snapshot {
  seq: number;
  ts: string;
  cpu: CpuInfo;
  gpu: GpuInfo;
  ram: RamInfo;
  disk: DiskInfo;
  models: LoadedModelInfo[];
  alerts: AlertInfo[];
  platform: string;
}

export interface StartupPhase {
  name: string;
  duration_ms: number;
  status: string;
  detail: string;
}

export interface StartupInfo {
  started_at: string;
  ready_at: string | null;
  total_ms: number;
  ready: boolean;
  version: string;
  phases: StartupPhase[];
}

export interface StartupHistoryItem {
  id: string;
  app_version: string;
  started_at: string;
  ready_at: string | null;
  total_ms: number;
  ok: boolean;
  error: string;
  phases: StartupPhase[];
}

export interface SystemInfo {
  app: string;
  version: string;
  platform: string;
  python: string;
  host: string;
  port: number;
  gpu: { available: boolean; name: string; total_mb: number; error: string };
  data_dir: string;
  frontend_built: boolean;
  reserve_vram_gb: number;
  reserve_ram_gb: number;
  disk_free_gb: number;
}

export interface HealthInfo {
  status: string;
  version: string;
  ready: boolean;
  data_dir: string;
}

export interface Measurement {
  id: string;
  model_id: string;
  variant_id: string;
  device: string;
  precision: string;
  peak_vram_gb: number;
  steady_vram_gb: number;
  ram_gb: number;
  load_ms: number;
  measured_at: string;
  sample_json: Record<string, unknown>;
}

export interface ModelVariantInfo {
  id: string;
  model_id: string;
  label: string;
  device: string;
  precision: string;
  vram_estimate_gb: number;
  ram_estimate_gb: number;
  disk_gb: number;
  install_state: string;
  install_path: string;
  installed_bytes: number;
  source: Record<string, unknown>;
  measurement?: Measurement | null;
}

export interface ModelInfo {
  id: string;
  name: string;
  category: "stt" | "tts" | "clone" | string;
  adapter: string;
  description: string;
  license: string;
  license_url: string;
  commercial: boolean;
  russian_status: "confirmed" | "verify" | "none" | string;
  languages: string[];
  capabilities: string[];
  warnings: string[];
  requires_exclusive: boolean;
  requires_consent: boolean;
  watermark: boolean;
  is_custom: boolean;
  installed: boolean;
  variants: ModelVariantInfo[];
  created_at: string;
  updated_at: string;
}

export interface DownloadInfo {
  id: string;
  model_id: string;
  variant_id: string;
  status: string;
  bytes_total: number;
  bytes_done: number;
  speed_bps: number;
  resumable: boolean;
  dest_path: string;
  error: string;
  created_at: string;
  updated_at: string;
}

export interface ResourceOption {
  id: string;
  label: string;
  model_id?: string;
  variant_id?: string;
  reclaim_gb?: number;
  would_fit?: boolean;
}

export interface ResourcePlan {
  model_id: string;
  variant_id: string;
  model_name: string;
  device: string;
  precision: string;
  need_vram_gb: number;
  free_vram_gb: number;
  need_ram_gb: number;
  free_ram_gb: number;
  verdict: "fits" | "tight" | "no";
  margin_gb: number;
  reason: string;
  options: ResourceOption[];
  source: string;
}

export interface TaskInfo {
  id: string;
  type: string;
  status: string;
  priority: number;
  model_id: string;
  voice_id: string | null;
  device: string;
  precision: string;
  language: string;
  text: string;
  queued_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  queue_ms: number;
  load_ms: number;
  infer_ms: number;
  post_ms: number;
  total_ms: number;
  rtf_infer: number;
  rtf_total: number;
  audio_duration_sec: number;
  peak_cpu_pct: number;
  peak_gpu_pct: number;
  peak_vram_mb: number;
  peak_ram_mb: number;
  peak_gpu_temp_c: number;
  warnings: string[];
  error_code: string;
  error_message: string;
  output_paths: string[];
  progress?: {
    status?: string;
    phase?: string;
    progress?: Record<string, unknown>;
    plan?: ResourcePlan;
    load_ms?: number;
    timings?: Record<string, number>;
    [key: string]: unknown;
  };
  result?: {
    text?: string;
    segments?: TranscriptSegment[];
    language?: string;
    audio_duration_sec?: number;
    output_path?: string;
    chunks?: number;
    [key: string]: unknown;
  } | null;
  params?: Record<string, unknown>;
}

export interface TranscriptWord {
  start: number;
  end: number;
  text: string;
  probability?: number;
}

export interface TranscriptSegment {
  start: number;
  end: number;
  text: string;
  words?: TranscriptWord[];
}

export interface VoiceInfo {
  id: string;
  name: string;
  kind: "builtin" | "cloned" | "designed" | string;
  model_id: string;
  engine_voice_id: string;
  language: string;
  gender: string;
  description: string;
  reference_path: string;
  duration_sec: number;
  quality_score: number | null;
  quality_json: {
    reference_text?: string;
    issues?: string[];
    warnings?: string[];
    score?: number;
    snr_db?: number;
    clipping_ratio?: number;
    [key: string]: unknown;
  };
  consent_accepted: boolean;
  license: string;
  commercial: boolean;
  preview_path: string;
  model_name: string;
  model_installed: boolean;
  has_reference: boolean;
  created_at: string;
}

export interface SettingsPayload {
  values: Record<string, unknown>;
  profiles: {
    id: string;
    name: string;
    scope: string;
    model_id: string;
    values: Record<string, unknown>;
    is_default: boolean;
  }[];
}

export interface QueuePayload {
  tasks: TaskInfo[];
  counts: { queued: number; running: number; awaiting: number };
}
