const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const source = fs.readFileSync(path.resolve(__dirname, "../main.cjs"), "utf8");

test("packaged desktop uses local runtime resources and development keeps Docker fallback", () => {
  assert.match(source, /LocalRuntimeManager/);
  assert.match(source, /app\.isPackaged/);
  assert.match(source, /process\.resourcesPath/);
  assert.match(source, /runtime["'], ["']python/);
  assert.match(source, /app\.asar\.unpacked/);
  assert.match(source, /postgresModulePath/);
  assert.match(source, /serviceManager\.ensureRunning/);
  assert.match(source, /COMIC_PIPELINE_DESKTOP_RUNTIME/);
});

test("desktop shutdown stops the owned runtime before quitting", () => {
  assert.match(source, /app\.on\(["']before-quit["']/);
  assert.match(source, /localRuntimeManager\.stop\(\)/);
  assert.match(source, /shutdownComplete/);
});

test("database password is generated randomly and stored through safeStorage", () => {
  assert.match(source, /safeStorage\.isEncryptionAvailable\(\)/);
  assert.match(source, /crypto\.randomBytes\(32\)/);
  assert.match(source, /databasePassword/);
  assert.doesNotMatch(source, /databasePassword:\s*["']comic_pipeline["']/);
});

test("provider keys are loaded from safeStorage and injected into the owned backend", () => {
  assert.match(source, /textApiKey/);
  assert.match(source, /imageApiKey/);
  assert.match(source, /saveProviderSecrets/);
  assert.match(source, /desktopManagedSecrets:\s*app\.isPackaged/);
});
