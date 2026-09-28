const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const { createSecretStore } = require("../secret-store.cjs");

function fakeSafeStorage(available = true) {
  return {
    isEncryptionAvailable: () => available,
    encryptString: (value) => Buffer.from(`encrypted:${[...value].reverse().join("")}`, "utf8"),
    decryptString: (value) => [...value.toString("utf8").replace(/^encrypted:/, "")].reverse().join(""),
  };
}

test("secret store persists provider and database credentials only in encrypted form", (context) => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "comic-secret-store-"));
  context.after(() => fs.rmSync(directory, { recursive: true, force: true }));
  const filePath = path.join(directory, "secrets.json");
  const store = createSecretStore({ filePath, safeStorage: fakeSafeStorage() });

  store.set("textApiKey", "text-secret-value");
  store.set("imageApiKey", "image-secret-value");
  store.set("databasePassword", "database-secret-value");

  const raw = fs.readFileSync(filePath, "utf8");
  assert.doesNotMatch(raw, /text-secret-value|image-secret-value|database-secret-value/);
  assert.equal(store.has("textApiKey"), true);
  assert.equal(store.get("textApiKey"), "text-secret-value");
  assert.equal(store.get("imageApiKey"), "image-secret-value");
  assert.equal(store.get("databasePassword"), "database-secret-value");
});

test("secret store rejects unapproved names and unavailable encryption", (context) => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "comic-secret-store-"));
  context.after(() => fs.rmSync(directory, { recursive: true, force: true }));
  const filePath = path.join(directory, "secrets.json");
  const store = createSecretStore({ filePath, safeStorage: fakeSafeStorage() });

  assert.throws(() => store.set("unknownSecret", "secret"), /not approved/);
  assert.throws(() => store.set("textApiKey", ""), /non-empty/);
  assert.throws(
    () => createSecretStore({ filePath, safeStorage: fakeSafeStorage(false) }).set("textApiKey", "secret"),
    /unavailable/,
  );
});

test("secret store removes a provider key without exposing it", (context) => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "comic-secret-store-"));
  context.after(() => fs.rmSync(directory, { recursive: true, force: true }));
  const store = createSecretStore({ filePath: path.join(directory, "secrets.json"), safeStorage: fakeSafeStorage() });

  store.set("imageApiKey", "secret");
  assert.equal(store.remove("imageApiKey"), true);
  assert.equal(store.remove("imageApiKey"), false);
  assert.equal(store.has("imageApiKey"), false);
  assert.equal(store.get("imageApiKey"), "");
});

test("secret store falls back to copy-and-remove when Windows rejects atomic rename", (context) => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "comic-secret-store-"));
  context.after(() => fs.rmSync(directory, { recursive: true, force: true }));
  const filePath = path.join(directory, "secrets.json");
  const fileSystem = Object.create(fs);
  fileSystem.renameSync = () => {
    const error = new Error("cross-device link not permitted");
    error.code = "EXDEV";
    throw error;
  };
  const store = createSecretStore({ filePath, safeStorage: fakeSafeStorage(), fileSystem });

  store.set("databasePassword", "database-secret-value");

  assert.equal(store.get("databasePassword"), "database-secret-value");
  assert.equal(fs.existsSync(`${filePath}.${process.pid}.tmp`), false);
  assert.doesNotMatch(fs.readFileSync(filePath, "utf8"), /database-secret-value/);
});
