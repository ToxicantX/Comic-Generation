const fs = require("node:fs");
const crypto = require("node:crypto");
const path = require("node:path");
const { pathToFileURL } = require("node:url");
const { app, BrowserWindow, dialog, ipcMain, Notification, safeStorage, shell } = require("electron");
const { autoUpdater } = require("electron-updater");
const { LocalRuntimeManager } = require("./local-runtime.cjs");
const { createSecretStore } = require("./secret-store.cjs");
const {
  ServiceManager,
  normalizeServiceUrl,
  probeConsole,
  waitForConsole,
} = require("./service-manager.cjs");
const { buildWindowsRuntimePaths } = require("./runtime-paths.cjs");
const { UpdateManager } = require("./update-manager.cjs");
const {
  IPC_CHANNELS,
  assertNoArguments,
  isAllowedIpcChannel,
  isAllowedRendererUrl,
  normalizeExternalUrl,
  normalizeNotificationPayload,
  normalizeProviderSecrets,
  validateApprovedDirectoryKey,
  validateNovelFilePath,
} = require("./native-capabilities.cjs");

const APP_ROOT = path.resolve(__dirname, "..");
const SERVICE_URL = normalizeServiceUrl(process.env.COMIC_PIPELINE_DESKTOP_URL);
const SPLASH_URL = pathToFileURL(path.join(__dirname, "splash.html")).href;
let mainWindow = null;
let serviceManager = null;
let localRuntimeManager = null;
let runtimePaths = null;
let startupRunning = false;
let runtimeMode = "starting";
let shutdownRunning = false;
let shutdownComplete = false;
let shutdownPromise = null;
let secretStore = null;
let updateManager = null;

function currentRuntimePaths() {
  if (!runtimePaths) throw new Error("Desktop runtime paths are not initialized.");
  return runtimePaths;
}

function approvedDirectories() {
  const paths = currentRuntimePaths();
  return {
    output: paths.outputDirectory,
    backups: paths.backupsDirectory,
    logs: paths.logsDirectory,
  };
}

function packagedResourceRoot() {
  return app.isPackaged
    ? path.join(process.resourcesPath, "runtime", "app")
    : APP_ROOT;
}

function packagedPythonPath() {
  return app.isPackaged
    ? path.join(process.resourcesPath, "runtime", "python", "python.exe")
    : (process.env.COMIC_PIPELINE_PYTHON_PATH || "python");
}

function packagedPostgresModulePath() {
  return app.isPackaged
    ? path.join(
      process.resourcesPath,
      "app.asar.unpacked",
      "node_modules",
      "embedded-postgres",
      "dist",
      "index.js",
    )
    : "";
}

function shouldUseLocalRuntime() {
  const configured = String(process.env.COMIC_PIPELINE_DESKTOP_RUNTIME || "").trim().toLowerCase();
  if (configured === "docker") return false;
  if (configured === "local") return true;
  return app.isPackaged;
}

function desktopSecretStore() {
  if (!safeStorage.isEncryptionAvailable()) {
    throw new Error("Windows 凭据加密不可用，无法安全启动本地数据库。");
  }
  secretStore ||= createSecretStore({
    safeStorage,
    filePath: path.join(currentRuntimePaths().configDirectory, "desktop-secrets.json"),
  });
  return secretStore;
}

function databasePassword() {
  const store = desktopSecretStore();
  if (!store.has("databasePassword")) {
    store.set("databasePassword", crypto.randomBytes(32).toString("base64url"));
  }
  return store.get("databasePassword");
}

function providerSecrets() {
  const store = desktopSecretStore();
  return {
    textApiKey: store.has("textApiKey") ? store.get("textApiKey") : "",
    imageApiKey: store.has("imageApiKey") ? store.get("imageApiKey") : "",
  };
}

function createLocalRuntimeManager() {
  const resourceRoot = packagedResourceRoot();
  const pythonPath = packagedPythonPath();
  const postgresModulePath = packagedPostgresModulePath();
  const secrets = providerSecrets();
  if (app.isPackaged) {
    for (const requiredPath of [
      resourceRoot,
      pythonPath,
      postgresModulePath,
      path.join(resourceRoot, "console", "server.py"),
    ]) {
      if (!fs.existsSync(requiredPath)) throw new Error(`桌面运行资源缺失：${requiredPath}`);
    }
  }
  return new LocalRuntimeManager({
    runtimePaths: currentRuntimePaths(),
    databasePassword: databasePassword(),
    pythonCommand: pythonPath,
    pythonPath,
    backendScript: path.join(resourceRoot, "console", "server.py"),
    backendCwd: resourceRoot,
    resourceRoot,
    postgresModulePath,
    textApiKey: secrets.textApiKey,
    imageApiKey: secrets.imageApiKey,
    desktopManagedSecrets: app.isPackaged,
    logger: ({ source, message }) => desktopLog(`${source}: ${message}`),
  });
}

async function saveProviderSecrets(secrets) {
  const store = desktopSecretStore();
  for (const [name, value] of Object.entries(secrets)) store.set(name, value);
  if (runtimeMode !== "local" || !localRuntimeManager) return { saved: true, restarted: false };

  sendStartupStatus({ phase: "restarting", message: "正在安全更新模型凭据..." });
  const stopped = await localRuntimeManager.stop();
  if (!stopped.ok) throw new Error("本地运行时未能安全停止，请查看桌面日志。");
  localRuntimeManager = createLocalRuntimeManager();
  await localRuntimeManager.start();
  if (!await waitForConsole(SERVICE_URL, { probe: probeConsole, timeoutMs: 90000 })) {
    throw new Error("模型凭据已保存，但本地控制台重启超时。");
  }
  sendStartupStatus({ phase: "ready", message: "模型凭据已安全更新。" });
  return { saved: true, restarted: true };
}

function logPath() {
  const directory = currentRuntimePaths().logsDirectory;
  fs.mkdirSync(directory, { recursive: true });
  return path.join(directory, "desktop.log");
}

function desktopLog(message) {
  const normalized = String(message || "").replace(/[\r\n]+/g, " ").slice(0, 4000);
  fs.appendFileSync(logPath(), `${new Date().toISOString()} ${normalized}\n`, "utf8");
}

function sendStartupStatus(status) {
  desktopLog(`${status.phase || "status"}: ${status.message || ""} ${status.detail || ""}`);
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send(IPC_CHANNELS.STARTUP_STATUS, status);
  }
}

function sendUpdateState(state) {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send(IPC_CHANNELS.UPDATE_STATE, state);
  }
}

async function stopOwnedRuntimeForQuit() {
  if (shutdownComplete) return;
  if (shutdownPromise) return shutdownPromise;
  shutdownRunning = true;
  sendStartupStatus({ phase: "stopping", message: "正在安全停止本地运行时..." });
  shutdownPromise = Promise.resolve()
    .then(() => localRuntimeManager?.stop())
    .catch((error) => desktopLog(`local runtime stop failed: ${error.message}`))
    .finally(() => {
      shutdownComplete = true;
    });
  return shutdownPromise;
}

function isServiceUrl(value) {
  try {
    return new URL(value).origin === new URL(SERVICE_URL).origin;
  } catch {
    return false;
  }
}

function openSafeExternal(value) {
  return shell.openExternal(normalizeExternalUrl(value), { activate: true });
}

function requestSafeExternal(value) {
  Promise.resolve()
    .then(() => openSafeExternal(value))
    .catch((error) => desktopLog(`external link rejected: ${error.message}`));
}

function validateTrustedSender(event) {
  const senderUrl = event.senderFrame?.url || event.sender.getURL();
  if (!mainWindow || event.sender !== mainWindow.webContents || !isAllowedRendererUrl(senderUrl, SERVICE_URL, SPLASH_URL)) {
    throw new Error("Desktop capability request rejected.");
  }
}

function registerIpcHandler(channel, validate, handler) {
  if (!isAllowedIpcChannel(channel)) {
    throw new Error(`IPC channel is not whitelisted: ${channel}`);
  }
  ipcMain.handle(channel, async (event, ...args) => {
    validateTrustedSender(event);
    const input = validate(args);
    return handler(input);
  });
}

function validateSingleArgument(args, validate) {
  if (!Array.isArray(args) || args.length !== 1) {
    throw new TypeError("Desktop capability requires exactly one argument.");
  }
  return validate(args[0]);
}

function registerDesktopIpcHandlers() {
  registerIpcHandler(IPC_CHANNELS.RETRY_STARTUP, assertNoArguments, () => startWorkspace());
  registerIpcHandler(IPC_CHANNELS.OPEN_LOG, assertNoArguments, () => shell.showItemInFolder(logPath()));
  registerIpcHandler(IPC_CHANNELS.GET_INFO, assertNoArguments, () => ({
    platform: process.platform,
    version: app.getVersion(),
    serviceUrl: SERVICE_URL,
    runtimeMode,
    directories: {
      output: currentRuntimePaths().outputDirectory,
      backups: currentRuntimePaths().backupsDirectory,
      logs: currentRuntimePaths().logsDirectory,
    },
  }));
  registerIpcHandler(IPC_CHANNELS.SELECT_NOVEL_FILE, assertNoArguments, async () => {
    const result = await dialog.showOpenDialog(mainWindow, {
      title: "选择小说文件",
      properties: ["openFile"],
      filters: [{ name: "小说文本", extensions: ["txt", "md"] }],
    });
    if (result.canceled || result.filePaths.length !== 1) return { canceled: true };
    const filePath = validateNovelFilePath(result.filePaths[0]);
    const stat = fs.statSync(filePath);
    if (!stat.isFile()) throw new TypeError("Selected novel path is not a file.");
    return {
      canceled: false,
      file: {
        path: filePath,
        name: path.basename(filePath),
        extension: path.extname(filePath).toLowerCase(),
      },
    };
  });
  registerIpcHandler(
    IPC_CHANNELS.OPEN_APPROVED_DIRECTORY,
    (args) => validateSingleArgument(args, validateApprovedDirectoryKey),
    async (key) => {
      const directory = approvedDirectories()[key];
      fs.mkdirSync(directory, { recursive: true });
      const error = await shell.openPath(directory);
      return { opened: error === "", error: error || null };
    },
  );
  registerIpcHandler(
    IPC_CHANNELS.SHOW_NOTIFICATION,
    (args) => validateSingleArgument(args, normalizeNotificationPayload),
    (payload) => {
      if (!Notification.isSupported()) return { shown: false, reason: "unsupported" };
      new Notification(payload).show();
      return { shown: true };
    },
  );
  registerIpcHandler(
    IPC_CHANNELS.OPEN_EXTERNAL,
    (args) => validateSingleArgument(args, normalizeExternalUrl),
    async (url) => {
      await openSafeExternal(url);
      return { opened: true };
    },
  );
  registerIpcHandler(
    IPC_CHANNELS.SAVE_PROVIDER_SECRETS,
    (args) => validateSingleArgument(args, normalizeProviderSecrets),
    saveProviderSecrets,
  );
  registerIpcHandler(IPC_CHANNELS.GET_UPDATE_STATE, assertNoArguments, () => updateManager.getState());
  registerIpcHandler(IPC_CHANNELS.CHECK_FOR_UPDATES, assertNoArguments, () => updateManager.checkNow());
  registerIpcHandler(IPC_CHANNELS.INSTALL_UPDATE, assertNoArguments, () => updateManager.installNow());
}

function protectNavigation(window) {
  window.webContents.setWindowOpenHandler(({ url }) => {
    if (isServiceUrl(url)) window.loadURL(url);
    else requestSafeExternal(url);
    return { action: "deny" };
  });
  window.webContents.on("will-navigate", (event, url) => {
    if (isServiceUrl(url) || url === SPLASH_URL) return;
    event.preventDefault();
    requestSafeExternal(url);
  });
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 1180,
    minHeight: 720,
    show: false,
    backgroundColor: "#0b0e13",
    autoHideMenuBar: true,
    title: "漫画流水线",
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  protectNavigation(mainWindow);
  mainWindow.once("ready-to-show", () => mainWindow.show());
  mainWindow.on("closed", () => { mainWindow = null; });
  mainWindow.loadFile(path.join(__dirname, "splash.html"));
}

async function startWorkspace() {
  if (startupRunning || !mainWindow) return;
  startupRunning = true;
  try {
    sendStartupStatus({ phase: "checking", message: "正在检查漫画流水线后台..." });
    let result;
    if (await probeConsole(SERVICE_URL)) {
      runtimeMode = "existing";
      result = { ok: true, reused: true, serviceUrl: SERVICE_URL };
    } else if (shouldUseLocalRuntime()) {
      runtimeMode = "local";
      sendStartupStatus({ phase: "starting", message: "正在启动本地 PostgreSQL 和漫画流水线后台..." });
      localRuntimeManager ||= createLocalRuntimeManager();
      result = await localRuntimeManager.start();
      sendStartupStatus({ phase: "waiting", message: "本地运行时已启动，正在等待控制台就绪..." });
      if (!await waitForConsole(SERVICE_URL, { probe: probeConsole, timeoutMs: 90000 })) {
        throw new Error("本地控制台启动超时，请查看桌面日志。");
      }
    } else {
      runtimeMode = "docker";
      result = await serviceManager.ensureRunning(sendStartupStatus);
    }
    if (!result.ok) {
      sendStartupStatus({ ...result, phase: "failed" });
      return;
    }
    sendStartupStatus({ phase: "ready", message: result.reused ? "正在打开已运行的工作台..." : "启动完成，正在打开工作台..." });
    await mainWindow.loadURL(SERVICE_URL);
  } catch (error) {
    sendStartupStatus({ phase: "failed", message: "桌面应用启动失败。", detail: error.message });
  } finally {
    startupRunning = false;
  }
}

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (!mainWindow) return;
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.focus();
  });

  app.whenReady().then(() => {
    runtimePaths = buildWindowsRuntimePaths({
      appDataDirectory: app.getPath("appData"),
      documentsDirectory: app.getPath("documents"),
    });
    serviceManager = new ServiceManager({ appRoot: APP_ROOT, serviceUrl: SERVICE_URL });
    updateManager = new UpdateManager({
      currentVersion: app.getVersion(),
      isPackaged: app.isPackaged,
      updater: autoUpdater,
      onStateChange: sendUpdateState,
      beforeInstall: stopOwnedRuntimeForQuit,
    });
    registerDesktopIpcHandlers();
    createWindow();
    updateManager.start();
    mainWindow.webContents.once("did-finish-load", startWorkspace);
  });
}

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

app.on("before-quit", (event) => {
  if (shutdownComplete) return;
  event.preventDefault();
  if (shutdownRunning) return;
  stopOwnedRuntimeForQuit().finally(() => app.quit());
});
