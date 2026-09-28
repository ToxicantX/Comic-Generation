const { contextBridge, ipcRenderer } = require("electron");

const INVOKE_CHANNELS = Object.freeze({
  GET_INFO: "desktop:get-info",
  OPEN_LOG: "desktop:open-log",
  RETRY_STARTUP: "desktop:retry-startup",
  SELECT_NOVEL_FILE: "desktop:select-novel-file",
  OPEN_APPROVED_DIRECTORY: "desktop:open-approved-directory",
  SHOW_NOTIFICATION: "desktop:show-notification",
  OPEN_EXTERNAL: "desktop:open-external",
  SAVE_PROVIDER_SECRETS: "desktop:save-provider-secrets",
  GET_UPDATE_STATE: "desktop:get-update-state",
  CHECK_FOR_UPDATES: "desktop:check-for-updates",
  INSTALL_UPDATE: "desktop:install-update",
});
const EVENT_CHANNELS = Object.freeze({
  STARTUP_STATUS: "desktop:startup-status",
  UPDATE_STATE: "desktop:update-state",
});
const invokeWhitelist = new Set(Object.values(INVOKE_CHANNELS));
const eventWhitelist = new Set(Object.values(EVENT_CHANNELS));
const approvedDirectoryKeys = new Set(["output", "backups", "logs"]);

function invoke(channel, ...args) {
  if (!invokeWhitelist.has(channel)) throw new Error("IPC channel is not allowed.");
  return ipcRenderer.invoke(channel, ...args);
}

function subscribe(channel, listener) {
  if (!eventWhitelist.has(channel) || typeof listener !== "function") {
    throw new TypeError("IPC subscription is not allowed.");
  }
  const handler = (_event, value) => listener(value);
  ipcRenderer.on(channel, handler);
  return () => ipcRenderer.removeListener(channel, handler);
}

contextBridge.exposeInMainWorld("comicDesktop", {
  getInfo: () => invoke(INVOKE_CHANNELS.GET_INFO),
  openLog: () => invoke(INVOKE_CHANNELS.OPEN_LOG),
  retryStartup: () => invoke(INVOKE_CHANNELS.RETRY_STARTUP),
  selectNovelFile: () => invoke(INVOKE_CHANNELS.SELECT_NOVEL_FILE),
  openApprovedDirectory: (key) => {
    if (typeof key !== "string" || !approvedDirectoryKeys.has(key)) {
      throw new TypeError("Directory is not approved by the desktop application.");
    }
    return invoke(INVOKE_CHANNELS.OPEN_APPROVED_DIRECTORY, key);
  },
  showNotification: (payload) => invoke(INVOKE_CHANNELS.SHOW_NOTIFICATION, payload),
  openExternal: (url) => invoke(INVOKE_CHANNELS.OPEN_EXTERNAL, url),
  saveProviderSecrets: (secrets) => invoke(INVOKE_CHANNELS.SAVE_PROVIDER_SECRETS, secrets),
  getUpdateState: () => invoke(INVOKE_CHANNELS.GET_UPDATE_STATE),
  checkForUpdates: () => invoke(INVOKE_CHANNELS.CHECK_FOR_UPDATES),
  installUpdate: () => invoke(INVOKE_CHANNELS.INSTALL_UPDATE),
  onStartupStatus: (listener) => subscribe(EVENT_CHANNELS.STARTUP_STATUS, listener),
  onUpdateState: (listener) => subscribe(EVENT_CHANNELS.UPDATE_STATE, listener),
});
