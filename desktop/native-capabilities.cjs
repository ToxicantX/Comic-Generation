const path = require("node:path");

const IPC_CHANNELS = Object.freeze({
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
  UPDATE_STATE: "desktop:update-state",
  STARTUP_STATUS: "desktop:startup-status",
});

const APPROVED_DIRECTORY_KEYS = Object.freeze(["output", "backups", "logs"]);
const ipcChannelWhitelist = new Set(Object.values(IPC_CHANNELS));
const approvedDirectoryKeySet = new Set(APPROVED_DIRECTORY_KEYS);

function isAllowedIpcChannel(channel) {
  return typeof channel === "string" && ipcChannelWhitelist.has(channel);
}

function assertNoArguments(args) {
  if (!Array.isArray(args) || args.length !== 0) {
    throw new TypeError("This desktop capability does not accept arguments.");
  }
}

function validateNovelFilePath(value) {
  if (typeof value !== "string" || value.length === 0 || value.length > 32767 || value.includes("\0")) {
    throw new TypeError("Novel file path must be a non-empty string.");
  }
  if (!path.isAbsolute(value)) {
    throw new TypeError("Novel file path must be absolute.");
  }
  const extension = path.extname(value).toLowerCase();
  if (extension !== ".txt" && extension !== ".md") {
    throw new TypeError("Only .txt and .md novel files are allowed.");
  }
  return path.normalize(value);
}

function validateApprovedDirectoryKey(value) {
  if (typeof value !== "string" || !approvedDirectoryKeySet.has(value)) {
    throw new TypeError("Directory is not approved by the desktop application.");
  }
  return value;
}

function normalizeNotificationPayload(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new TypeError("Notification payload must be an object.");
  }
  const keys = Object.keys(value);
  if (keys.some((key) => key !== "title" && key !== "body")) {
    throw new TypeError("Notification payload contains unsupported fields.");
  }
  if (typeof value.title !== "string") {
    throw new TypeError("Notification title must be a string.");
  }
  const title = value.title.trim();
  if (title.length === 0 || title.length > 80) {
    throw new TypeError("Notification title must contain 1 to 80 characters.");
  }
  if (value.body !== undefined && typeof value.body !== "string") {
    throw new TypeError("Notification body must be a string.");
  }
  const body = (value.body || "").trim();
  if (body.length > 500) {
    throw new TypeError("Notification body must not exceed 500 characters.");
  }
  return { title, body };
}

function normalizeExternalUrl(value) {
  if (typeof value !== "string" || value.length === 0 || value.length > 2048) {
    throw new TypeError("External URL must be a non-empty string.");
  }
  let url;
  try {
    url = new URL(value);
  } catch {
    throw new TypeError("External URL is invalid.");
  }
  if (url.protocol !== "https:" || url.username || url.password) {
    throw new TypeError("Only HTTPS external URLs without credentials are allowed.");
  }
  return url.href;
}

function normalizeProviderSecrets(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new TypeError("Provider secrets must be an object.");
  }
  const allowed = new Set(["textApiKey", "imageApiKey"]);
  if (Object.keys(value).some((key) => !allowed.has(key))) {
    throw new TypeError("Provider secrets contain unsupported fields.");
  }
  const result = {};
  for (const key of allowed) {
    if (value[key] === undefined) continue;
    if (typeof value[key] !== "string" || !value[key].trim() || value[key].length > 16384 || value[key].includes("\0")) {
      throw new TypeError(`${key} must be a non-empty string.`);
    }
    result[key] = value[key].trim();
  }
  if (Object.keys(result).length === 0) throw new TypeError("At least one provider secret is required.");
  return Object.freeze(result);
}

function isAllowedRendererUrl(value, serviceUrl, splashUrl) {
  if (typeof value !== "string" || value === "") return false;
  if (value === splashUrl) return true;
  try {
    return new URL(value).origin === new URL(serviceUrl).origin;
  } catch {
    return false;
  }
}

module.exports = {
  APPROVED_DIRECTORY_KEYS,
  IPC_CHANNELS,
  assertNoArguments,
  isAllowedIpcChannel,
  isAllowedRendererUrl,
  normalizeExternalUrl,
  normalizeNotificationPayload,
  normalizeProviderSecrets,
  validateApprovedDirectoryKey,
  validateNovelFilePath,
};
