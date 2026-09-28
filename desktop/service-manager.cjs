const http = require("node:http");
const { spawn } = require("node:child_process");

const DEFAULT_SERVICE_URL = "http://127.0.0.1:8199";

function normalizeServiceUrl(value = DEFAULT_SERVICE_URL) {
  const url = new URL(value);
  if (url.protocol !== "http:" || !["127.0.0.1", "localhost", "::1"].includes(url.hostname)) {
    throw new Error("桌面服务地址必须是本机 HTTP 地址");
  }
  url.pathname = "";
  url.search = "";
  url.hash = "";
  return url.toString().replace(/\/$/, "");
}

function probeConsole(serviceUrl, timeoutMs = 1500) {
  const target = new URL("/api/config", `${normalizeServiceUrl(serviceUrl)}/`);
  return new Promise((resolve) => {
    const request = http.get(target, { timeout: timeoutMs }, (response) => {
      response.resume();
      resolve(response.statusCode === 200);
    });
    request.on("timeout", () => request.destroy());
    request.on("error", () => resolve(false));
  });
}

function runCompose(appRoot, onOutput = () => {}) {
  return new Promise((resolve) => {
    const child = spawn("docker", ["compose", "up", "-d"], {
      cwd: appRoot,
      windowsHide: true,
      shell: false,
    });
    let output = "";
    const collect = (chunk) => {
      const text = chunk.toString();
      output = `${output}${text}`.slice(-24000);
      onOutput(text);
    };
    child.stdout.on("data", collect);
    child.stderr.on("data", collect);
    child.on("error", (error) => resolve({ ok: false, code: null, output, error: error.message }));
    child.on("close", (code) => resolve({ ok: code === 0, code, output, error: "" }));
  });
}

function waitForConsole(serviceUrl, options = {}) {
  const timeoutMs = options.timeoutMs ?? 90000;
  const intervalMs = options.intervalMs ?? 1000;
  const probe = options.probe ?? probeConsole;
  const started = Date.now();
  return new Promise((resolve) => {
    const check = async () => {
      if (await probe(serviceUrl)) return resolve(true);
      if (Date.now() - started >= timeoutMs) return resolve(false);
      setTimeout(check, intervalMs);
    };
    check();
  });
}

class ServiceManager {
  constructor(options) {
    this.appRoot = options.appRoot;
    this.serviceUrl = normalizeServiceUrl(options.serviceUrl ?? DEFAULT_SERVICE_URL);
    this.probe = options.probe ?? probeConsole;
    this.runCompose = options.runCompose ?? runCompose;
    this.waitForConsole = options.waitForConsole ?? waitForConsole;
  }

  async ensureRunning(onStatus = () => {}) {
    onStatus({ phase: "checking", message: "正在检查漫画流水线后台..." });
    if (await this.probe(this.serviceUrl)) {
      return { ok: true, reused: true, serviceUrl: this.serviceUrl, message: "后台已运行" };
    }

    onStatus({ phase: "starting", message: "正在启动数据库和漫画流水线后台..." });
    const compose = await this.runCompose(this.appRoot, (line) => {
      onStatus({ phase: "starting", message: "后台启动中...", detail: line.trim() });
    });
    if (!compose.ok) {
      return {
        ok: false,
        phase: "compose_failed",
        message: "无法启动本地后台。请确认 Docker Desktop 已启动。",
        detail: compose.error || compose.output || `docker compose 退出码 ${compose.code}`,
      };
    }

    onStatus({ phase: "waiting", message: "后台已启动，正在等待数据库和控制台就绪..." });
    const ready = await this.waitForConsole(this.serviceUrl, { probe: this.probe });
    if (!ready) {
      return {
        ok: false,
        phase: "timeout",
        message: "后台启动超时。可以查看 Docker 状态和桌面日志后重试。",
        detail: compose.output,
      };
    }
    return { ok: true, reused: false, serviceUrl: this.serviceUrl, message: "后台已就绪" };
  }
}

module.exports = {
  DEFAULT_SERVICE_URL,
  ServiceManager,
  normalizeServiceUrl,
  probeConsole,
  runCompose,
  waitForConsole,
};
