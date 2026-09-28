/// <reference types="vite/client" />

import type {
  ReviewCenterData,
  ReviewOutputBatchAction,
  ReviewQueueFilter,
  ReviewQueueItem,
  ReviewTarget,
  ReviewTimelineFilter,
  ReviewTimelineLimit,
  ReviewTimelineRange,
} from "./review/types";
import type {
  ConfigSnapshot,
  DesktopDirectoryKey,
  DesktopInfo,
  DesktopUpdateState,
  FetchModelsRequest,
  GenerationBackend,
  ModelTarget,
  ModelTestResult,
  SettingsActivity,
  SettingsHealth,
  SettingsSavePayload,
  SettingsSummary,
  TestModelRequest,
} from "./settings/types";
import type {
  TaskFileActionEvent,
  TaskFileEvent,
  TaskFilePreview,
  TaskFilter,
  TaskJob,
} from "./tasks/types";

declare global {
  interface ComicReviewCenterActions {
    refresh?: () => void;
    queueFilterChange?: (value: ReviewQueueFilter) => void;
    timelineFilterChange?: (value: ReviewTimelineFilter) => void;
    timelineRangeChange?: (value: ReviewTimelineRange) => void;
    timelineLimitChange?: (value: ReviewTimelineLimit) => void;
    selectQueueItem?: (value: string) => void;
    selectTimelineItem?: (value: string) => void;
    openTarget?: (target: ReviewTarget) => void;
    reviewOutputBatch?: (item: ReviewQueueItem, action: ReviewOutputBatchAction) => void;
  }

  interface ComicTaskCenterActions {
    filterChange?: (value: TaskFilter) => void;
    select?: (value: string) => void;
    cancel?: (value: string) => void;
    retry?: (value: string) => void;
    refresh?: () => void;
    previewFile?: (payload: TaskFileEvent) => void;
    downloadFile?: (payload: TaskFileEvent) => void;
    fileAction?: (payload: TaskFileActionEvent) => void;
  }

  interface ComicSettingsActions {
    save?: (payload: SettingsSavePayload) => void;
    healthCheck?: () => void;
    fetchModels?: (request: FetchModelsRequest) => void;
    testModel?: (request: TestModelRequest) => void;
    backendCheck?: () => void;
    backendStart?: (request: { wait_seconds: number }) => void;
    openDirectory?: (key: DesktopDirectoryKey) => void;
    checkUpdate?: () => void;
    installUpdate?: () => void;
  }

  interface Window {
    comicNotify?: (notification: import("./notifications/types").NotificationInput) => void;
    comicDialog?: (options: import("./dialogs/types").DialogOptions) => Promise<import("./dialogs/types").DialogResult>;
    __comicPendingNotifications?: import("./notifications/types").NotificationInput[];
    comicReviewCenter?: {
      update: (next: Partial<{
        reviewCenter: ReviewCenterData;
        queueFilter: ReviewQueueFilter;
        timelineFilter: ReviewTimelineFilter;
        timelineRange: ReviewTimelineRange;
        timelineLimit: ReviewTimelineLimit;
        selectedQueueItemId: string;
        selectedTimelineItemId: string;
      }>) => void;
      setActions: (actions: ComicReviewCenterActions) => void;
    };
    comicTaskCenter?: {
      update: (next: Partial<{
        jobs: TaskJob[];
        filter: TaskFilter;
        selectedJobId: string;
        taskFilePreview: TaskFilePreview | null;
      }>) => void;
      setActions: (actions: ComicTaskCenterActions) => void;
    };
    comicSettings?: {
      update: (next: Partial<{
        config: ConfigSnapshot;
        settingsSummary: SettingsSummary | null;
        settingsHealth: SettingsHealth | null;
        generationBackend: GenerationBackend | null;
        novelPath: string;
        defaultPages: string | number;
        encoding: string;
        modelOptions: Partial<Record<ModelTarget, string[]>>;
        modelListMessages: Partial<Record<ModelTarget, string>>;
        modelTestResults: Partial<Record<ModelTarget, ModelTestResult | null>>;
        activity: SettingsActivity;
        desktopInfo: DesktopInfo | null;
        desktopUpdate: DesktopUpdateState | null;
      }>) => void;
      setActions: (actions: ComicSettingsActions) => void;
    };
    comicDesktop?: {
      getInfo: () => Promise<DesktopInfo>;
      openLog: () => Promise<unknown>;
      retryStartup: () => Promise<unknown>;
      selectNovelFile: () => Promise<{ canceled: true } | { canceled: false; file: { path: string; name: string; extension: string } }>;
      openApprovedDirectory: (key: DesktopDirectoryKey) => Promise<{ opened: boolean; error?: string | null }>;
      showNotification: (payload: { title: string; body?: string }) => Promise<{ shown: boolean; reason?: string }>;
      openExternal: (url: string) => Promise<{ opened: boolean }>;
      saveProviderSecrets: (secrets: { textApiKey?: string; imageApiKey?: string }) => Promise<{ saved: boolean; restarted: boolean }>;
      getUpdateState: () => Promise<DesktopUpdateState>;
      checkForUpdates: () => Promise<DesktopUpdateState>;
      installUpdate: () => Promise<{ installing: boolean }>;
      onStartupStatus: (listener: (status: Record<string, unknown>) => void) => () => void;
      onUpdateState: (listener: (state: DesktopUpdateState) => void) => () => void;
    };
  }
}

declare module "*.vue" {
  import type { DefineComponent } from "vue";

  const component: DefineComponent<Record<string, never>, Record<string, never>, unknown>;
  export default component;
}
