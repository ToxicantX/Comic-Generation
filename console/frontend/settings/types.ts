export type ImageBackend = "direct_api" | "comfyui";
export type ModelTarget = "text" | "image";
export type DesktopDirectoryKey = "output" | "backups" | "logs";
export type DesktopUpdateStatus = "disabled" | "idle" | "checking" | "up-to-date" | "available" | "downloading" | "downloaded" | "installing" | "error";

export interface DesktopUpdateProgress {
  percent: number;
  transferred: number;
  total: number;
  bytesPerSecond: number;
}

export interface DesktopUpdateState {
  enabled: boolean;
  status: DesktopUpdateStatus;
  currentVersion: string;
  availableVersion: string | null;
  progress: DesktopUpdateProgress | null;
  lastCheckedAt: string | null;
  message: string;
}

export interface DesktopInfo {
  platform: string;
  version: string;
  serviceUrl: string;
  runtimeMode: string;
  directories: Record<DesktopDirectoryKey, string>;
}

export interface ProviderSnapshot {
  OPENAI_BASE_URL?: string;
  OPENAI_API_KEY_CONFIGURED?: boolean;
}

export interface DatabaseStatus {
  schema_ready?: boolean;
  error?: string;
  [key: string]: unknown;
}

export interface ConfigSnapshot {
  root?: string;
  config_path?: string;
  text_env_path?: string;
  image_env_path?: string;
  config: Record<string, string>;
  projects?: {
    active?: string;
    items?: Array<Record<string, unknown>>;
  };
  database?: DatabaseStatus;
  text?: ProviderSnapshot;
  image?: ProviderSnapshot;
}

export interface SettingsSummary {
  image_backend?: ImageBackend;
  models?: {
    novel_model?: string;
    image_model?: string;
    sources?: {
      novel_model?: string;
      image_model?: string;
    };
  };
  paths?: {
    output_root?: string;
    sources?: {
      output_root?: string;
    };
  };
  project?: {
    slug?: string;
    title?: string;
  };
  database?: DatabaseStatus;
}

export interface SettingsHealthCheck {
  name?: string;
  label?: string;
  ok?: boolean;
  message?: string;
  source?: string;
}

export interface SettingsHealth {
  ok?: boolean;
  checks?: SettingsHealthCheck[];
  settings?: SettingsSummary;
}

export interface PathStatus {
  path?: string;
  exists?: boolean;
  files?: number;
}

export interface GenerationBackend {
  ok?: boolean;
  image_backend?: ImageBackend;
  comfy_url?: string;
  port_open?: boolean;
  start_supported?: boolean;
  start_blocker?: string;
  message?: string;
  diagnostics?: GenerationBackend;
  provider?: {
    base_url?: string;
    api_key_configured?: boolean;
  };
  paths?: Record<string, PathStatus>;
  logs?: {
    stdout?: PathStatus & { tail?: string };
    stderr?: PathStatus & { tail?: string };
  };
  health?: {
    model_catalog?: {
      missing_nodes?: string[];
      missing_models?: string[];
    };
  };
}

export interface ModelTestResult {
  ok?: boolean;
  message?: string;
  dry_run?: boolean;
  detail?: {
    elapsed_seconds?: number;
  };
}

export interface SettingsActivity {
  saving?: boolean;
  checkingHealth?: boolean;
  checkingBackend?: boolean;
  startingBackend?: boolean;
  fetchingModels?: Partial<Record<ModelTarget, boolean>>;
  testingModels?: Partial<Record<ModelTarget, boolean>>;
}

export interface ModelProviderForm {
  model: string;
  baseUrl: string;
  apiKey: string;
  timeout: string;
  stream: boolean;
  quality: string;
}

export interface ImageBackendForm {
  imageBackend: ImageBackend;
  comfyUrl: string;
  comfyRoot: string;
  comfyCheckpoint: string;
  comfyLoraName: string;
  comfyLoraStrengthModel: string;
  comfyLoraStrengthClip: string;
  comfyControlnetName: string;
  comfyControlnetStrength: string;
  comfyControlnetStart: string;
  comfyControlnetEnd: string;
  comfySteps: string;
  comfyCfg: string;
  comfySampler: string;
  comfyScheduler: string;
  outputRoot: string;
}

export interface SettingsFormState {
  backend: ImageBackendForm;
  text: ModelProviderForm;
  image: ModelProviderForm;
}

export interface ProviderSavePayload {
  OPENAI_BASE_URL: string;
  OPENAI_API_KEY?: string;
}

export interface SettingsSavePayload {
  config: Record<string, string>;
  text: ProviderSavePayload;
  image: ProviderSavePayload;
}

export interface FetchModelsRequest {
  target: ModelTarget;
  base_url: string;
  api_key: string;
}

export interface TestModelRequest {
  target: ModelTarget;
  timeout: number;
  live: boolean;
  config: SettingsSavePayload;
}
