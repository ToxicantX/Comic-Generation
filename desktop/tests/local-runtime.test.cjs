const assert = require("node:assert/strict");
const { EventEmitter } = require("node:events");
const test = require("node:test");

const {
  BACKEND_PORT,
  DATABASE_PORT,
  LocalRuntimeManager,
  redactLog,
} = require("../local-runtime.cjs");

function runtimePaths() {
  return {
    userDataRoot: "C:\\Users\\Ada\\AppData\\Roaming\\Comic Pipeline",
    configDirectory: "C:\\Users\\Ada\\AppData\\Roaming\\Comic Pipeline\\config",
    logsDirectory: "C:\\Users\\Ada\\AppData\\Roaming\\Comic Pipeline\\logs",
    backupsDirectory: "C:\\Users\\Ada\\AppData\\Roaming\\Comic Pipeline\\backups",
    databaseDirectory: "C:\\Users\\Ada\\AppData\\Roaming\\Comic Pipeline\\database",
    novelsDirectory: "C:\\Users\\Ada\\Documents\\Comic Pipeline\\novels",
    projectsDirectory: "C:\\Users\\Ada\\Documents\\Comic Pipeline\\projects",
    outputDirectory: "C:\\Users\\Ada\\Documents\\Comic Pipeline\\output",
  };
}

function fakeChild({ exitOnKill = true } = {}) {
  const child = new EventEmitter();
  child.pid = 1234;
  child.exitCode = null;
  child.stdout = new EventEmitter();
  child.stderr = new EventEmitter();
  child.killCalls = [];
  child.kill = (signal) => {
    child.killCalls.push(signal || "SIGTERM");
    if (exitOnKill) {
      child.exitCode = 0;
      queueMicrotask(() => child.emit("exit", 0, null));
    }
    return true;
  };
  return child;
}

function fakePostgres(events, overrides = {}) {
  return {
    initialise: async () => events.push("postgres.initialise"),
    start: async () => events.push("postgres.start"),
    createDatabase: async (name) => events.push(`postgres.create:${name}`),
    stop: async () => events.push("postgres.stop"),
    ...overrides,
  };
}

function managerOptions(overrides = {}) {
  const events = overrides.events || [];
  const postgres = overrides.postgres || fakePostgres(events);
  const child = overrides.child || fakeChild();
  const spawned = [];
  return {
    events,
    postgres,
    child,
    spawned,
    options: {
      runtimePaths: runtimePaths(),
      backendExecutable: "C:\\Program Files\\Comic Pipeline\\backend.exe",
      databasePassword: "db-secret-value",
      createPostgres: async (options) => {
        events.push("postgres.create-runtime");
        overrides.onPostgresOptions?.(options);
        return postgres;
      },
      spawnBackend: (command, args, options) => {
        events.push("backend.spawn");
        spawned.push({ command, args, options });
        if (overrides.spawnError) throw overrides.spawnError;
        return child;
      },
      mkdir: async (directory) => events.push(`mkdir:${directory}`),
      pathExists: async () => overrides.initialized ?? false,
      environment: { BASE_ENV: "kept" },
      stopTimeoutMs: overrides.stopTimeoutMs || 50,
      logger: overrides.logger,
    },
  };
}

test("starts persistent loopback Postgres, creates the application database, and launches packaged backend", async () => {
  let postgresOptions;
  const fixture = managerOptions({ onPostgresOptions: (value) => { postgresOptions = value; } });
  const manager = new LocalRuntimeManager(fixture.options);

  const result = await manager.start();

  assert.deepEqual(fixture.events.filter((entry) => entry.startsWith("postgres.")), [
    "postgres.create-runtime",
    "postgres.initialise",
    "postgres.start",
    "postgres.create:comic_pipeline",
  ]);
  assert.equal(postgresOptions.databaseDir, runtimePaths().databaseDirectory);
  assert.equal(postgresOptions.port, DATABASE_PORT);
  assert.equal(postgresOptions.persistent, true);
  assert.deepEqual(postgresOptions.postgresFlags, ["-h", "127.0.0.1"]);
  assert.equal(result.serviceUrl, `http://127.0.0.1:${BACKEND_PORT}`);
  assert.equal(result.mode, "packaged");
  assert.equal(fixture.spawned[0].command, "C:\\Program Files\\Comic Pipeline\\backend.exe");
  assert.deepEqual(fixture.spawned[0].args, ["--host", "127.0.0.1", "--port", "8199"]);

  assert.equal((await manager.stop()).ok, true);
  assert.equal(fixture.child.killCalls.length, 1);
  assert.equal(fixture.events.at(-1), "postgres.stop");
});

test("concurrent and repeated start calls are idempotent", async () => {
  const fixture = managerOptions();
  const manager = new LocalRuntimeManager(fixture.options);

  const [first, concurrent] = await Promise.all([manager.start(), manager.start()]);
  const repeated = await manager.start();

  assert.equal(first.ok, true);
  assert.equal(concurrent.ok, true);
  assert.equal(repeated.reused, true);
  assert.equal(fixture.events.filter((entry) => entry === "postgres.create-runtime").length, 1);
  assert.equal(fixture.spawned.length, 1);
  await manager.stop();
});

test("backend launch failure rolls back an already-started Postgres runtime", async () => {
  const fixture = managerOptions({ spawnError: new Error("backend unavailable") });
  const manager = new LocalRuntimeManager(fixture.options);

  await assert.rejects(manager.start(), /backend unavailable/);

  assert.equal(fixture.events.includes("postgres.stop"), true);
  assert.equal(manager.state, "stopped");
  assert.equal(manager.postgresStarted, false);
});

test("Postgres start failure also invokes bounded rollback", async () => {
  const events = [];
  const postgres = fakePostgres(events, {
    start: async () => {
      events.push("postgres.start");
      throw new Error("postgres start failed");
    },
  });
  const fixture = managerOptions({ events, postgres });
  const manager = new LocalRuntimeManager(fixture.options);

  await assert.rejects(manager.start(), /postgres start failed/);

  assert.deepEqual(events.filter((entry) => entry.startsWith("postgres.")), [
    "postgres.create-runtime",
    "postgres.initialise",
    "postgres.start",
    "postgres.stop",
  ]);
  assert.equal(fixture.spawned.length, 0);
});

test("development launch receives isolated user paths and the local database URL", async () => {
  const fixture = managerOptions();
  delete fixture.options.backendExecutable;
  fixture.options.pythonCommand = { command: "py", args: ["-3.12", "-I"] };
  fixture.options.backendScript = "D:\\ComicApp\\console\\server.py";
  fixture.options.resourceRoot = "D:\\ComicApp";
  fixture.options.pythonPath = "C:\\Runtime\\python.exe";
  fixture.options.textApiKey = "text-provider-secret";
  fixture.options.imageApiKey = "image-provider-secret";
  fixture.options.desktopManagedSecrets = true;
  const manager = new LocalRuntimeManager(fixture.options);

  const result = await manager.start();
  const launch = fixture.spawned[0];

  assert.equal(result.mode, "development");
  assert.equal(launch.command, "py");
  assert.deepEqual(launch.args, [
    "-3.12",
    "-I",
    "D:\\ComicApp\\console\\server.py",
    "--host",
    "127.0.0.1",
    "--port",
    "8199",
  ]);
  assert.equal(launch.options.env.BASE_ENV, "kept");
  assert.equal(launch.options.env.COMIC_PIPELINE_CONFIG_PATH, `${runtimePaths().configDirectory}\\.env`);
  assert.equal(launch.options.env.COMIC_PIPELINE_TEXT_ENV_PATH, `${runtimePaths().configDirectory}\\text.env`);
  assert.equal(launch.options.env.COMIC_PIPELINE_IMAGE_ENV_PATH, `${runtimePaths().configDirectory}\\image.env`);
  assert.equal(launch.options.env.COMIC_PIPELINE_RESOURCE_ROOT, "D:\\ComicApp");
  assert.equal(launch.options.env.COMIC_PIPELINE_DATA_ROOT, runtimePaths().userDataRoot);
  assert.equal(launch.options.env.COMIC_PIPELINE_BACKUPS_DIR, runtimePaths().backupsDirectory);
  assert.equal(launch.options.env.COMIC_PIPELINE_PYTHON_PATH, "C:\\Runtime\\python.exe");
  assert.equal(launch.options.env.COMIC_PIPELINE_TEXT_API_KEY, "text-provider-secret");
  assert.equal(launch.options.env.COMIC_PIPELINE_IMAGE_API_KEY, "image-provider-secret");
  assert.equal(launch.options.env.COMIC_PIPELINE_DESKTOP_MANAGED_SECRETS, "1");
  assert.equal(launch.options.env.PYTHONNOUSERSITE, "1");
  assert.equal(launch.options.env.COMIC_PIPELINE_LOG_DIR, runtimePaths().logsDirectory);
  assert.equal(launch.options.env.COMIC_PIPELINE_NOVELS_DIR, runtimePaths().novelsDirectory);
  assert.equal(launch.options.env.COMIC_PIPELINE_PROJECTS_DIR, runtimePaths().projectsDirectory);
  assert.equal(launch.options.env.COMIC_PIPELINE_OUTPUT_ROOT, runtimePaths().outputDirectory);
  assert.equal(
    launch.options.env.COMIC_PIPELINE_DATABASE_URL,
    "postgresql://comic_pipeline:db-secret-value@127.0.0.1:54329/comic_pipeline",
  );
  assert.equal(launch.options.shell, false);
  await manager.stop();
});

test("Postgres and backend logs redact credentials and known secrets", async () => {
  const logs = [];
  let postgresOptions;
  const fixture = managerOptions({
    logger: (entry) => logs.push(entry.message),
    onPostgresOptions: (value) => { postgresOptions = value; },
  });
  const manager = new LocalRuntimeManager(fixture.options);
  await manager.start();

  postgresOptions.onLog("postgresql://comic_pipeline:db-secret-value@127.0.0.1:54329/comic_pipeline");
  fixture.child.stderr.emit("data", Buffer.from("Authorization: Bearer provider-token api_key=provider-key db-secret-value"));

  assert.ok(logs.every((line) => !/db-secret-value|provider-token|provider-key/.test(line)));
  assert.match(logs.join("\n"), /\[REDACTED\]/);
  assert.doesNotMatch(
    redactLog("password=hunter2 token=abc123 Bearer xyz", ["hunter2"]),
    /hunter2|abc123|xyz/,
  );
  await manager.stop();
});

test("startup logs expose each runtime stage without credentials", async () => {
  const logs = [];
  const fixture = managerOptions({ logger: (entry) => logs.push(`${entry.source}:${entry.message}`) });
  const manager = new LocalRuntimeManager(fixture.options);

  await manager.start();

  assert.deepEqual(logs, [
    "runtime:preparing runtime directories",
    "runtime:runtime directories ready",
    "runtime:loading embedded PostgreSQL runtime",
    "runtime:embedded PostgreSQL runtime loaded",
    "runtime:initialising PostgreSQL data directory",
    "runtime:PostgreSQL data directory initialised",
    "runtime:starting PostgreSQL",
    "runtime:PostgreSQL started",
    "runtime:ensuring application database",
    "runtime:application database ready",
    "runtime:starting Python backend",
    "runtime:Python backend process started",
  ]);
  assert.ok(logs.every((line) => !line.includes("db-secret-value")));
  await manager.stop();
});

test("stop is bounded when child and Postgres do not exit and never removes persistent data", async () => {
  const events = [];
  const postgres = fakePostgres(events, { stop: () => new Promise(() => {}) });
  const child = fakeChild({ exitOnKill: false });
  const fixture = managerOptions({ events, postgres, child, stopTimeoutMs: 15 });
  const manager = new LocalRuntimeManager(fixture.options);
  await manager.start();

  const startedAt = Date.now();
  const result = await manager.stop();
  const elapsed = Date.now() - startedAt;

  assert.equal(result.ok, false);
  assert.deepEqual(result.timedOut.sort(), ["backend", "postgres"]);
  assert.ok(elapsed < 250, `stop took ${elapsed}ms`);
  assert.deepEqual(child.killCalls, ["SIGTERM", "SIGKILL"]);
  assert.equal(fixture.options.mkdir.toString().includes("rm"), false);
});
