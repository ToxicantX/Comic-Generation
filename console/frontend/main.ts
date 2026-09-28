import { createApp, defineComponent, h, reactive } from "vue";

import DialogHost from "./dialogs/DialogHost.vue";
import { DIALOG_EVENT, type DialogOptions, type DialogResult } from "./dialogs/types";
import ToastHost from "./notifications/ToastHost.vue";
import { NOTIFICATION_EVENT, type NotificationInput } from "./notifications/types";
import ReviewCenterView from "./review/ReviewCenterView.vue";
import type {
  ReviewCenterData,
  ReviewQueueFilter,
  ReviewTimelineFilter,
  ReviewTimelineLimit,
  ReviewTimelineRange,
} from "./review/types";
import SettingsView from "./settings/SettingsView.vue";
import type {
  ConfigSnapshot,
  DesktopDirectoryKey,
  DesktopInfo,
  DesktopUpdateState,
  FetchModelsRequest,
  ModelTarget,
  SettingsActivity,
  SettingsSavePayload,
  TestModelRequest,
} from "./settings/types";
import TaskCenterView from "./tasks/TaskCenterView.vue";
import type {
  TaskFileActionEvent,
  TaskFileEvent,
  TaskFilePreview,
  TaskFilter,
  TaskJob,
} from "./tasks/types";

const toastHost = document.getElementById("appToastStack");

if (toastHost) {
  createApp(ToastHost).mount(toastHost);
  window.comicNotify = (notification: NotificationInput) => {
    window.dispatchEvent(new CustomEvent(NOTIFICATION_EVENT, { detail: notification }));
  };
  const pending = window.__comicPendingNotifications?.splice(0) ?? [];
  pending.forEach((notification) => window.comicNotify?.(notification));
}

const dialogHost = document.getElementById("appDialogHost");

if (dialogHost) {
  createApp(DialogHost).mount(dialogHost);
  window.comicDialog = (options: DialogOptions) => new Promise<DialogResult>((resolve) => {
    window.dispatchEvent(new CustomEvent(DIALOG_EVENT, { detail: { options, resolve } }));
  });
}

const reviewHost = document.getElementById("reviewCenterApp");

if (reviewHost) {
  const view = reactive({
    reviewCenter: {} as ReviewCenterData,
    queueFilter: "all" as ReviewQueueFilter,
    timelineFilter: "all" as ReviewTimelineFilter,
    timelineRange: "all" as ReviewTimelineRange,
    timelineLimit: 40 as ReviewTimelineLimit,
    selectedQueueItemId: "",
    selectedTimelineItemId: "",
  });
  let actions: ComicReviewCenterActions = {};

  createApp(defineComponent({
    setup: () => () => h(ReviewCenterView, {
      ...view,
      onRefresh: () => actions.refresh?.(),
      onQueueFilterChange: (value: ReviewQueueFilter) => actions.queueFilterChange?.(value),
      onTimelineFilterChange: (value: ReviewTimelineFilter) => actions.timelineFilterChange?.(value),
      onTimelineRangeChange: (value: ReviewTimelineRange) => actions.timelineRangeChange?.(value),
      onTimelineLimitChange: (value: ReviewTimelineLimit) => actions.timelineLimitChange?.(value),
      onSelectQueueItem: (value: string) => actions.selectQueueItem?.(value),
      onSelectTimelineItem: (value: string) => actions.selectTimelineItem?.(value),
      onOpenTarget: (target) => actions.openTarget?.(target),
      onReviewOutputBatch: (item, action) => actions.reviewOutputBatch?.(item, action),
    }),
  })).mount(reviewHost);

  window.comicReviewCenter = {
    update(next) {
      Object.assign(view, next);
    },
    setActions(next) {
      actions = next;
    },
  };
}

const taskHost = document.getElementById("taskCenterApp");

if (taskHost) {
  const view = reactive({
    jobs: [] as TaskJob[],
    filter: "all" as TaskFilter,
    selectedJobId: "",
    taskFilePreview: null as TaskFilePreview | null,
  });
  let actions: ComicTaskCenterActions = {};

  createApp(defineComponent({
    setup: () => () => h(TaskCenterView, {
      ...view,
      onFilterChange: (value: TaskFilter) => actions.filterChange?.(value),
      onSelect: (value: string) => actions.select?.(value),
      onCancel: (value: string) => actions.cancel?.(value),
      onRetry: (value: string) => actions.retry?.(value),
      onRefresh: () => actions.refresh?.(),
      onPreviewFile: (payload: TaskFileEvent) => actions.previewFile?.(payload),
      onDownloadFile: (payload: TaskFileEvent) => actions.downloadFile?.(payload),
      onFileAction: (payload: TaskFileActionEvent) => actions.fileAction?.(payload),
    }),
  })).mount(taskHost);

  window.comicTaskCenter = {
    update(next) {
      Object.assign(view, next);
    },
    setActions(next) {
      actions = next;
    },
  };
}

const settingsHost = document.getElementById("settingsApp");

if (settingsHost) {
  const view = reactive({
    config: { config: {} } as ConfigSnapshot,
    settingsSummary: null,
    settingsHealth: null,
    generationBackend: null,
    novelPath: "",
    defaultPages: "8",
    encoding: "utf-8",
    modelOptions: { text: [], image: [] } as Record<ModelTarget, string[]>,
    modelListMessages: { text: "", image: "" } as Record<ModelTarget, string>,
    modelTestResults: { text: null, image: null },
    activity: {} as SettingsActivity,
    desktopInfo: null as DesktopInfo | null,
    desktopUpdate: null as DesktopUpdateState | null,
  });
  let actions: ComicSettingsActions = {};

  createApp(defineComponent({
    setup: () => () => h(SettingsView, {
      ...view,
      onSave: (payload: SettingsSavePayload) => actions.save?.(payload),
      onHealthCheck: () => actions.healthCheck?.(),
      onFetchModels: (request: FetchModelsRequest) => actions.fetchModels?.(request),
      onTestModel: (request: TestModelRequest) => actions.testModel?.(request),
      onBackendCheck: () => actions.backendCheck?.(),
      onBackendStart: (request: { wait_seconds: number }) => actions.backendStart?.(request),
      onOpenDirectory: (key: DesktopDirectoryKey) => actions.openDirectory?.(key),
      onCheckUpdate: () => actions.checkUpdate?.(),
      onInstallUpdate: () => actions.installUpdate?.(),
    }),
  })).mount(settingsHost);

  window.comicSettings = {
    update(next) {
      Object.assign(view, next);
    },
    setActions(next) {
      actions = next;
    },
  };
}
