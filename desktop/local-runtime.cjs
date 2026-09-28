const fs = require("node:fs");
const path = require("node:path");
const { spawn } = require("node:child_process");
const { pathToFileURL } = require("node:url");

const LOOPBACK_HOST = "127.0.0.1";
const DATABASE_PORT = 54329;
const BACKEND_PORT = 8199;
const DATABASE_NAME = "comic_pipeline";
const DATABASE_USER = "comic_pipeline";
const DEFAULT_STOP_TIMEOUT_MS = 5000;

function requireNonEmpty(value, label) {
  if (typeof value !== "string" || !value.trim()) {
    throw new TypeError(`${label} must be a non-empty string.`);
  }
  return value.trim();
}

function requireRuntimePaths(runtimePaths) {
  const required = [
    "configDirectory",
    "logsDirectory",
    "databaseDirectory",
    "novelsDirectory",
    "projectsDirectory",
    "outputDirectory",
  ];
  if (!runtimePaths || typeof runtimePaths !== "object") {
    throw new TypeError("runtimePaths is required.");
  }
  for (const key of required) requireNonEmpty(runtimePaths[key], `runtimePaths.${key}`);
  return runtimePaths;
}

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function redactLog(value, secrets = []) {
  let text = value instanceof Error ? (value.stack || value.message) : String(value ?? "");
  text = text
    .replace(/\b(postgres(?:ql)?:\/\/)([^:\s/@]+):([^@\s/]+)@/gi, "$1[REDACTED]:[REDACTED]@")
    .replace(/\bBearer\s+[^\s,;]+/gi, "Bearer [REDACTED]")
    .replace(/((?:api[_-]?key|authorization|password|secret|token)\s*[:=]\s*)([^\s,;]+)/gi, "$1[REDACTED]");
  for (const secret of secrets) {
    if (typeof secret === "string" && secret.length >= 4) {
      text = text.replace(new RegExp(escapeRegExp(secret), "g"), "[REDACTED]");
    }
  }
  return text.slice(0, 16000);
}

function databaseUrl(password) {
  const user = encodeURIComponent(DATABASE_USER);
  const encodedPassword = encodeURIComponent(password);
  return `postgresql://${user}:${encodedPassword}@${LOOPBACK_HOST}:${DATABASE_PORT}/${DATABASE_NAME}`;
}

function buildBackendEnvironment(runtimePaths, password, baseEnvironment = process.env, options = {}) {
  const environment = {
    ...baseEnvironment,
    COMIC_PIPELINE_CONFIG_PATH: path.join(runtimePaths.configDirectory, ".env"),
    COMIC_PIPELINE_TEXT_ENV_PATH: path.join(runtimePaths.configDirectory, "text.env"),
    COMIC_PIPELINE_IMAGE_ENV_PATH: path.join(runtimePaths.configDirectory, "image.env"),
    COMIC_PIPELINE_LOG_DIR: runtimePaths.logsDirectory,
    COMIC_PIPELINE_NOVELS_DIR: runtimePaths.novelsDirectory,
    COMIC_PIPELINE_PROJECTS_DIR: runtimePaths.projectsDirectory,
    COMIC_PIPELINE_OUTPUT_ROOT: runtimePaths.outputDirectory,
    COMIC_PIPELINE_DATABASE_URL: databaseUrl(password),
    PYTHONNOUSERSITE: "1",
  };
  if (runtimePaths.userDataRoot) environment.COMIC_PIPELINE_DATA_ROOT = runtimePaths.userDataRoot;
  if (runtimePaths.backupsDirectory) environment.COMIC_PIPELINE_BACKUPS_DIR = runtimePaths.backupsDirectory;
  if (options.resourceRoot) environment.COMIC_PIPELINE_RESOURCE_ROOT = options.resourceRoot;
  if (options.pythonPath) environment.COMIC_PIPELINE_PYTHON_PATH = options.pythonPath;
  if (options.textApiKey) environment.COMIC_PIPELINE_TEXT_API_KEY = options.textApiKey;
  if (options.imageApiKey) environment.COMIC_PIPELINE_IMAGE_API_KEY = options.imageApiKey;
  if (options.desktopManagedSecrets) environment.COMIC_PIPELINE_DESKTOP_MANAGED_SECRETS = "1";
  return environment;
}

function normalizePythonCommand(value) {
  if (value === undefined) return { command: "python", args: [] };
  if (typeof value === "string") return { command: requireNonEmpty(value, "pythonCommand"), args: [] };
  if (Array.isArray(value) && value.length > 0) {
    return {
      command: requireNonEmpty(value[0], "pythonCommand[0]"),
      args: value.slice(1).map((entry, index) => requireNonEmpty(entry, `pythonCommand[${index + 1}]`)),
    };
  }
  if (value && typeof value === "object") {
    return {
      command: requireNonEmpty(value.command, "pythonCommand.command"),
      args: Array.isArray(value.args)
        ? value.args.map((entry, index) => requireNonEmpty(entry, `pythonCommand.args[${index}]`))
        : [],
    };
  }
  throw new TypeError("pythonCommand must be a string, a non-empty array, or a command object.");
}

function buildBackendLaunch(options) {
  const commonArgs = ["--host", LOOPBACK_HOST, "--port", String(BACKEND_PORT)];
  if (options.backendExecutable) {
    const command = requireNonEmpty(options.backendExecutable, "backendExecutable");
    return { command, args: commonArgs, cwd: options.backendCwd || path.dirname(command), mode: "packaged" };
  }

  const python = normalizePythonCommand(options.pythonCommand);
  const script = requireNonEmpty(
    options.backendScript || path.resolve(__dirname, "..", "console", "server.py"),
    "backendScript",
  );
  return {
    command: python.command,
    args: [...python.args, script, ...commonArgs],
    cwd: options.backendCwd || path.dirname(script),
    mode: "development",
  };
}

async function defaultCreatePostgres(options, modulePath = "") {
  const specifier = modulePath ? pathToFileURL(modulePath).href : "embedded-postgres";
  const { default: EmbeddedPostgres } = await import(specifier);
  return new EmbeddedPostgres(options);
}

function isDatabaseAlreadyPresent(error) {
  return error?.code === "42P04" || /database .* already exists/i.test(String(error?.message || error));
}

function waitForSpawn(child) {
  if (child?.pid) return Promise.resolve();
  return new Promise((resolve, reject) => {
    if (!child || typeof child.once !== "function") {
      reject(new TypeError("spawnBackend must return a child process."));
      return;
    }
    child.once("spawn", resolve);
    child.once("error", reject);
  });
}

function settleWithin(operation, timeoutMs) {
  return new Promise((resolve) => {
    let settled = false;
    const finish = (result) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve(result);
    };
    const timer = setTimeout(() => finish({ ok: false, timedOut: true }), timeoutMs);
    Promise.resolve()
      .then(operation)
      .then(() => finish({ ok: true, timedOut: false }))
      .catch((error) => finish({ ok: false, timedOut: false, error }));
  });
}

function terminateChild(child) {
  if (!child || child.exitCode !== null && child.exitCode !== undefined) return Promise.resolve();
  return new Promise((resolve, reject) => {
    if (typeof child.once !== "function" || typeof child.kill !== "function") {
      reject(new TypeError("Backend process cannot be stopped."));
      return;
    }
    child.once("exit", resolve);
    child.once("error", reject);
    try {
      if (child.kill() === false && child.exitCode !== null && child.exitCode !== undefined) resolve();
    } catch (error) {
      reject(error);
    }
  });
}

class LocalRuntimeManager {
  constructor(options = {}) {
    this.runtimePaths = requireRuntimePaths(options.runtimePaths);
    this.databasePassword = requireNonEmpty(options.databasePassword || "comic_pipeline", "databasePassword");
    this.backendLaunch = buildBackendLaunch(options);
    this.createPostgres = options.createPostgres
      || ((postgresOptions) => defaultCreatePostgres(postgresOptions, options.postgresModulePath));
    this.spawnBackend = options.spawnBackend || spawn;
    this.mkdir = options.mkdir || ((directory) => fs.promises.mkdir(directory, { recursive: true }));
    this.pathExists = options.pathExists || (async (target) => {
      try {
        await fs.promises.access(target);
        return true;
      } catch {
        return false;
      }
    });
    this.baseEnvironment = options.environment || process.env;
    this.resourceRoot = options.resourceRoot || "";
    this.pythonPath = options.pythonPath || "";
    this.textApiKey = options.textApiKey || "";
    this.imageApiKey = options.imageApiKey || "";
    this.desktopManagedSecrets = options.desktopManagedSecrets === true;
    this.logger = typeof options.logger === "function" ? options.logger : () => {};
    this.stopTimeoutMs = Number.isFinite(options.stopTimeoutMs) && options.stopTimeoutMs > 0
      ? options.stopTimeoutMs
      : DEFAULT_STOP_TIMEOUT_MS;
    this.state = "stopped";
    this.postgres = null;
    this.postgresStarted = false;
    this.backendProcess = null;
    this.startPromise = null;
    this.stopPromise = null;
    this.lastResult = null;
  }

  log(source, value) {
    const message = redactLog(value, [this.databasePassword, this.textApiKey, this.imageApiKey]);
    if (message.trim()) this.logger({ source, message });
  }

  start() {
    if (this.state === "running") return Promise.resolve({ ...this.lastResult, reused: true });
    if (this.startPromise) return this.startPromise;
    this.state = "starting";
    this.startPromise = this.startInternal()
      .then((result) => {
        this.state = "running";
        this.lastResult = result;
        return result;
      })
      .catch(async (error) => {
        this.log("runtime", error);
        await this.stopResources();
        this.state = "stopped";
        this.lastResult = null;
        throw error;
      })
      .finally(() => {
        this.startPromise = null;
      });
    return this.startPromise;
  }

  async startInternal() {
    this.log("runtime", "preparing runtime directories");
    await Promise.all([
      this.mkdir(this.runtimePaths.configDirectory),
      this.mkdir(this.runtimePaths.logsDirectory),
      this.mkdir(this.runtimePaths.databaseDirectory),
      this.mkdir(this.runtimePaths.novelsDirectory),
      this.mkdir(this.runtimePaths.projectsDirectory),
      this.mkdir(this.runtimePaths.outputDirectory),
    ]);
    this.log("runtime", "runtime directories ready");

    this.log("runtime", "loading embedded PostgreSQL runtime");
    this.postgres = await this.createPostgres({
      databaseDir: this.runtimePaths.databaseDirectory,
      port: DATABASE_PORT,
      user: DATABASE_USER,
      password: this.databasePassword,
      authMethod: "scram-sha-256",
      persistent: true,
      postgresFlags: ["-h", LOOPBACK_HOST],
      onLog: (message) => this.log("postgres", message),
      onError: (error) => this.log("postgres", error),
    });
    this.log("runtime", "embedded PostgreSQL runtime loaded");
    for (const method of ["initialise", "start", "createDatabase", "stop"]) {
      if (typeof this.postgres?.[method] !== "function") {
        throw new TypeError(`Postgres runtime is missing ${method}().`);
      }
    }

    const initialized = await this.pathExists(path.join(this.runtimePaths.databaseDirectory, "PG_VERSION"));
    if (!initialized) {
      this.log("runtime", "initialising PostgreSQL data directory");
      await this.postgres.initialise();
      this.log("runtime", "PostgreSQL data directory initialised");
    }
    // stop() is safe before a successful start and also cleans up a partial start.
    this.postgresStarted = true;
    this.log("runtime", "starting PostgreSQL");
    await this.postgres.start();
    this.log("runtime", "PostgreSQL started");
    try {
      this.log("runtime", "ensuring application database");
      await this.postgres.createDatabase(DATABASE_NAME);
    } catch (error) {
      if (!isDatabaseAlreadyPresent(error)) throw error;
    }
    this.log("runtime", "application database ready");

    const environment = buildBackendEnvironment(
      this.runtimePaths,
      this.databasePassword,
      this.baseEnvironment,
      {
        resourceRoot: this.resourceRoot,
        pythonPath: this.pythonPath,
        textApiKey: this.textApiKey,
        imageApiKey: this.imageApiKey,
        desktopManagedSecrets: this.desktopManagedSecrets,
      },
    );
    this.log("runtime", "starting Python backend");
    this.backendProcess = this.spawnBackend(this.backendLaunch.command, this.backendLaunch.args, {
      cwd: this.backendLaunch.cwd,
      env: environment,
      shell: false,
      windowsHide: true,
      stdio: ["ignore", "pipe", "pipe"],
    });
    this.bindBackendLogs(this.backendProcess);
    await waitForSpawn(this.backendProcess);
    this.log("runtime", "Python backend process started");

    return Object.freeze({
      ok: true,
      reused: false,
      mode: this.backendLaunch.mode,
      serviceUrl: `http://${LOOPBACK_HOST}:${BACKEND_PORT}`,
      database: Object.freeze({ host: LOOPBACK_HOST, port: DATABASE_PORT, name: DATABASE_NAME }),
    });
  }

  bindBackendLogs(child) {
    child?.stdout?.on?.("data", (chunk) => this.log("backend.stdout", chunk.toString()));
    child?.stderr?.on?.("data", (chunk) => this.log("backend.stderr", chunk.toString()));
    child?.on?.("error", (error) => this.log("backend", error));
    child?.once?.("exit", (code, signal) => {
      this.log("backend", `process exited (code=${code ?? "null"}, signal=${signal ?? "null"})`);
      if (this.state === "running") this.state = "failed";
    });
  }

  stop() {
    if (this.stopPromise) return this.stopPromise;
    this.stopPromise = Promise.resolve(this.startPromise)
      .catch(() => undefined)
      .then(async () => {
        if (!this.backendProcess && !this.postgresStarted) {
          this.state = "stopped";
          return { ok: true, timedOut: [], errors: [] };
        }
        this.state = "stopping";
        const result = await this.stopResources();
        this.state = result.ok ? "stopped" : "failed";
        if (result.ok) this.lastResult = null;
        return result;
      })
      .finally(() => {
        this.stopPromise = null;
      });
    return this.stopPromise;
  }

  async stopResources() {
    const backend = this.backendProcess;
    const postgres = this.postgresStarted ? this.postgres : null;
    const [backendResult, postgresResult] = await Promise.all([
      settleWithin(() => terminateChild(backend), this.stopTimeoutMs),
      settleWithin(() => postgres?.stop(), this.stopTimeoutMs),
    ]);

    if (backendResult.timedOut) {
      try { backend?.kill?.("SIGKILL"); } catch (error) { this.log("runtime", error); }
    }
    const results = [["backend", backendResult], ["postgres", postgresResult]];
    const timedOut = results.filter(([, result]) => result.timedOut).map(([name]) => name);
    const errors = results
      .filter(([, result]) => result.error)
      .map(([resource, result]) => ({ resource, message: redactLog(result.error, [this.databasePassword]) }));
    for (const resource of timedOut) this.log("runtime", `${resource} stop timed out`);
    for (const error of errors) this.log("runtime", `${error.resource} stop failed: ${error.message}`);

    if (backendResult.ok) this.backendProcess = null;
    if (postgresResult.ok) {
      this.postgresStarted = false;
      this.postgres = null;
    }
    return { ok: timedOut.length === 0 && errors.length === 0, timedOut, errors };
  }
}

module.exports = {
  BACKEND_PORT,
  DATABASE_NAME,
  DATABASE_PORT,
  DATABASE_USER,
  DEFAULT_STOP_TIMEOUT_MS,
  LOOPBACK_HOST,
  LocalRuntimeManager,
  buildBackendEnvironment,
  buildBackendLaunch,
  databaseUrl,
  redactLog,
};
