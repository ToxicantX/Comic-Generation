const DEFAULT_AUTO_CHECK_DELAY_MS = 5000;

function cloneState(state) {
  return {
    ...state,
    progress: state.progress ? { ...state.progress } : null,
  };
}

function versionFrom(info, fallback = null) {
  const version = info && typeof info.version === "string" ? info.version.trim() : "";
  return version || fallback;
}

function progressFrom(value) {
  const number = (key) => Number.isFinite(Number(value?.[key])) ? Number(value[key]) : 0;
  return {
    percent: Math.min(100, Math.max(0, number("percent"))),
    transferred: Math.max(0, number("transferred")),
    total: Math.max(0, number("total")),
    bytesPerSecond: Math.max(0, number("bytesPerSecond")),
  };
}

class UpdateManager {
  constructor({
    currentVersion,
    isPackaged,
    updater,
    onStateChange = () => {},
    beforeInstall = async () => {},
    schedule = setTimeout,
    now = () => new Date().toISOString(),
    autoCheckDelayMs = DEFAULT_AUTO_CHECK_DELAY_MS,
  }) {
    this.updater = updater;
    this.enabled = Boolean(isPackaged && updater);
    this.onStateChange = onStateChange;
    this.beforeInstall = beforeInstall;
    this.schedule = schedule;
    this.now = now;
    this.autoCheckDelayMs = autoCheckDelayMs;
    this.started = false;
    this.state = {
      enabled: this.enabled,
      status: this.enabled ? "idle" : "disabled",
      currentVersion: String(currentVersion || "0.0.0"),
      availableVersion: null,
      progress: null,
      lastCheckedAt: null,
      message: this.enabled ? "尚未检查更新" : "开发模式不连接更新服务",
    };
  }

  getState() {
    return cloneState(this.state);
  }

  publish(patch) {
    this.state = { ...this.state, ...patch };
    const state = this.getState();
    this.onStateChange(state);
    return state;
  }

  fail() {
    return this.publish({
      status: "error",
      progress: null,
      lastCheckedAt: this.now(),
      message: "无法连接更新服务，请稍后重试",
    });
  }

  bindEvents() {
    this.updater.on("checking-for-update", () => {
      this.publish({ status: "checking", progress: null, message: "正在检查更新..." });
    });
    this.updater.on("update-available", (info) => {
      this.publish({
        status: "available",
        availableVersion: versionFrom(info),
        progress: null,
        lastCheckedAt: this.now(),
        message: "发现新版本，正在后台下载",
      });
    });
    this.updater.on("update-not-available", () => {
      this.publish({
        status: "up-to-date",
        availableVersion: null,
        progress: null,
        lastCheckedAt: this.now(),
        message: "当前已是最新版本",
      });
    });
    this.updater.on("download-progress", (progress) => {
      this.publish({
        status: "downloading",
        progress: progressFrom(progress),
        message: "正在后台下载更新",
      });
    });
    this.updater.on("update-downloaded", (info) => {
      this.publish({
        status: "downloaded",
        availableVersion: versionFrom(info, this.state.availableVersion),
        progress: null,
        message: "新版本已下载，可重启完成升级",
      });
    });
    this.updater.on("error", () => this.fail());
  }

  start() {
    if (this.started) return this.getState();
    this.started = true;
    if (!this.enabled) return this.getState();

    this.updater.autoDownload = true;
    this.updater.autoInstallOnAppQuit = true;
    this.bindEvents();
    const timer = this.schedule(() => this.checkNow(), this.autoCheckDelayMs);
    timer?.unref?.();
    return this.getState();
  }

  async checkNow() {
    if (!this.enabled) return this.getState();
    if (["checking", "downloading", "downloaded", "installing"].includes(this.state.status)) {
      return this.getState();
    }
    this.publish({ status: "checking", progress: null, message: "正在检查更新..." });
    try {
      await this.updater.checkForUpdates();
      return this.getState();
    } catch {
      return this.fail();
    }
  }

  async installNow() {
    if (!this.enabled || this.state.status !== "downloaded") {
      throw new Error("Update is not ready to install.");
    }
    await this.beforeInstall();
    this.publish({ status: "installing", message: "正在退出并安装更新..." });
    this.updater.quitAndInstall(false, true);
    return { installing: true };
  }
}

module.exports = { UpdateManager };
