const assert = require("node:assert/strict");
const { EventEmitter } = require("node:events");
const test = require("node:test");

const { UpdateManager } = require("../update-manager.cjs");

class FakeUpdater extends EventEmitter {
  constructor() {
    super();
    this.autoDownload = false;
    this.autoInstallOnAppQuit = false;
    this.checkCalls = 0;
    this.installCalls = [];
  }

  async checkForUpdates() {
    this.checkCalls += 1;
    return null;
  }

  quitAndInstall(...args) {
    this.installCalls.push(args);
  }
}

test("development mode never contacts the update provider", async () => {
  const updater = new FakeUpdater();
  const manager = new UpdateManager({
    currentVersion: "0.1.0",
    isPackaged: false,
    updater,
    schedule: (callback) => callback(),
  });

  manager.start();
  const result = await manager.checkNow();

  assert.equal(updater.checkCalls, 0);
  assert.deepEqual(result, {
    enabled: false,
    status: "disabled",
    currentVersion: "0.1.0",
    availableVersion: null,
    progress: null,
    lastCheckedAt: null,
    message: "开发模式不连接更新服务",
  });
});

test("packaged mode automatically checks and configures unattended download", async () => {
  const updater = new FakeUpdater();
  let scheduled = null;
  const manager = new UpdateManager({
    currentVersion: "0.1.0",
    isPackaged: true,
    updater,
    schedule: (callback, delay) => {
      scheduled = { callback, delay };
    },
    autoCheckDelayMs: 5000,
  });

  manager.start();
  assert.equal(updater.autoDownload, true);
  assert.equal(updater.autoInstallOnAppQuit, true);
  assert.equal(scheduled.delay, 5000);

  await scheduled.callback();
  assert.equal(updater.checkCalls, 1);
  assert.equal(manager.getState().status, "checking");
});

test("updater events expose available version, progress, and downloaded state", () => {
  const updater = new FakeUpdater();
  const states = [];
  const manager = new UpdateManager({
    currentVersion: "0.1.0",
    isPackaged: true,
    updater,
    onStateChange: (state) => states.push(state),
    now: () => "2026-09-29T00:00:00.000Z",
  });
  manager.start();

  updater.emit("update-available", { version: "0.2.0" });
  updater.emit("download-progress", {
    percent: 42.25,
    transferred: 425,
    total: 1000,
    bytesPerSecond: 200,
  });
  updater.emit("update-downloaded", { version: "0.2.0" });

  assert.equal(states.some((state) => state.status === "available"), true);
  assert.deepEqual(states.at(-2).progress, {
    percent: 42.25,
    transferred: 425,
    total: 1000,
    bytesPerSecond: 200,
  });
  assert.deepEqual(manager.getState(), {
    enabled: true,
    status: "downloaded",
    currentVersion: "0.1.0",
    availableVersion: "0.2.0",
    progress: null,
    lastCheckedAt: "2026-09-29T00:00:00.000Z",
    message: "新版本已下载，可重启完成升级",
  });
});

test("manual install is allowed only after download and waits for runtime shutdown", async () => {
  const updater = new FakeUpdater();
  const calls = [];
  const manager = new UpdateManager({
    currentVersion: "0.1.0",
    isPackaged: true,
    updater,
    beforeInstall: async () => calls.push("runtime-stopped"),
  });
  manager.start();

  await assert.rejects(() => manager.installNow(), /not ready/i);
  updater.emit("update-downloaded", { version: "0.2.0" });
  const result = await manager.installNow();

  assert.deepEqual(calls, ["runtime-stopped"]);
  assert.deepEqual(updater.installCalls, [[false, true]]);
  assert.deepEqual(result, { installing: true });
  assert.equal(manager.getState().status, "installing");
});

test("update failures never expose raw provider errors", async () => {
  const updater = new FakeUpdater();
  updater.checkForUpdates = async () => {
    throw new Error("GET https://token:secret@example.test/latest.yml failed with 401");
  };
  const manager = new UpdateManager({
    currentVersion: "0.1.0",
    isPackaged: true,
    updater,
  });
  manager.start();

  const state = await manager.checkNow();

  assert.equal(state.status, "error");
  assert.equal(state.message, "无法连接更新服务，请稍后重试");
  assert.doesNotMatch(JSON.stringify(state), /token|secret|example\.test/i);
});
