const assert = require("node:assert/strict");
const path = require("node:path");
const test = require("node:test");
const {
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
} = require("../native-capabilities.cjs");

test("IPC channel whitelist contains every desktop capability and no arbitrary channels", () => {
  for (const channel of Object.values(IPC_CHANNELS)) assert.equal(isAllowedIpcChannel(channel), true);
  assert.equal(isAllowedIpcChannel("desktop:run-command"), false);
  assert.equal(isAllowedIpcChannel(null), false);
});

test("update capabilities are explicitly allowlisted", () => {
  assert.equal(isAllowedIpcChannel("desktop:get-update-state"), true);
  assert.equal(isAllowedIpcChannel("desktop:check-for-updates"), true);
  assert.equal(isAllowedIpcChannel("desktop:install-update"), true);
  assert.equal(isAllowedIpcChannel("desktop:update-state"), true);
});

test("argument-free capabilities reject unexpected input", () => {
  assert.doesNotThrow(() => assertNoArguments([]));
  assert.throws(() => assertNoArguments(["unexpected"]), /does not accept arguments/);
});

test("novel file validation only accepts absolute txt and md paths", () => {
  const txtPath = path.resolve("novels", "story.TXT");
  const mdPath = path.resolve("novels", "story.md");
  assert.equal(validateNovelFilePath(txtPath), path.normalize(txtPath));
  assert.equal(validateNovelFilePath(mdPath), path.normalize(mdPath));
  assert.throws(() => validateNovelFilePath("story.txt"), /absolute/);
  assert.throws(() => validateNovelFilePath(path.resolve("story.pdf")), /Only .txt and .md/);
  assert.throws(() => validateNovelFilePath(`${txtPath}\0.exe`), /non-empty string/);
});

test("approved directory validation exposes fixed main-process identifiers", () => {
  assert.deepEqual(APPROVED_DIRECTORY_KEYS, ["output", "backups", "logs"]);
  for (const key of APPROVED_DIRECTORY_KEYS) assert.equal(validateApprovedDirectoryKey(key), key);
  assert.throws(() => validateApprovedDirectoryKey("C:\\Users"), /not approved/);
  assert.throws(() => validateApprovedDirectoryKey("../output"), /not approved/);
});

test("notification validation normalizes bounded title and body", () => {
  assert.deepEqual(
    normalizeNotificationPayload({ title: "  生成完成  ", body: "  第一章已完成  " }),
    { title: "生成完成", body: "第一章已完成" },
  );
  assert.deepEqual(normalizeNotificationPayload({ title: "任务完成" }), { title: "任务完成", body: "" });
  assert.throws(() => normalizeNotificationPayload({ title: "" }), /1 to 80/);
  assert.throws(() => normalizeNotificationPayload({ title: "a".repeat(81) }), /1 to 80/);
  assert.throws(() => normalizeNotificationPayload({ title: "完成", body: "a".repeat(501) }), /500/);
  assert.throws(() => normalizeNotificationPayload({ title: "完成", icon: "file:///tmp/icon.png" }), /unsupported/);
});

test("external URL validation only permits credential-free HTTPS", () => {
  assert.equal(normalizeExternalUrl("https://example.com/docs?q=1"), "https://example.com/docs?q=1");
  assert.throws(() => normalizeExternalUrl("http://example.com"), /Only HTTPS/);
  assert.throws(() => normalizeExternalUrl("https://user:secret@example.com"), /without credentials/);
  assert.throws(() => normalizeExternalUrl("file:///C:/Windows/System32"), /Only HTTPS/);
  assert.throws(() => normalizeExternalUrl("javascript:alert(1)"), /Only HTTPS/);
  assert.throws(() => normalizeExternalUrl("not a url"), /invalid/);
});

test("provider secret validation accepts only non-empty text and image API keys", () => {
  assert.deepEqual(normalizeProviderSecrets({ textApiKey: " text-secret " }), { textApiKey: "text-secret" });
  assert.deepEqual(normalizeProviderSecrets({ imageApiKey: "image-secret" }), { imageApiKey: "image-secret" });
  assert.throws(() => normalizeProviderSecrets({}), /At least one/);
  assert.throws(() => normalizeProviderSecrets({ textApiKey: "" }), /non-empty/);
  assert.throws(() => normalizeProviderSecrets({ databasePassword: "secret" }), /unsupported/);
});

test("renderer URL validation accepts only the splash and configured service origin", () => {
  const serviceUrl = "http://127.0.0.1:8199";
  const splashUrl = "file:///C:/comic/desktop/splash.html";
  assert.equal(isAllowedRendererUrl(splashUrl, serviceUrl, splashUrl), true);
  assert.equal(isAllowedRendererUrl("http://127.0.0.1:8199/projects/1", serviceUrl, splashUrl), true);
  assert.equal(isAllowedRendererUrl("http://localhost:8199", serviceUrl, splashUrl), false);
  assert.equal(isAllowedRendererUrl("https://example.com", serviceUrl, splashUrl), false);
});
