const assert = require("node:assert/strict");
const { Readable } = require("node:stream");
const test = require("node:test");
const {
  buildMigrationManifest,
  reconcileDatabaseObjectCounts,
  sha256File,
  validateBackupSources,
} = require("../data-migration.cjs");
const { buildWindowsRuntimePaths } = require("../runtime-paths.cjs");

function runtimePaths() {
  return buildWindowsRuntimePaths({
    env: { APPDATA: "C:\\Users\\Ada\\AppData\\Roaming", USERPROFILE: "C:\\Users\\Ada" },
  });
}

function directoryInfo({ symlink = false } = {}) {
  return {
    isDirectory: () => !symlink,
    isFile: () => false,
    isSymbolicLink: () => symlink,
  };
}

test("migration manifest contains only the approved copy-only data sets", () => {
  const manifest = buildMigrationManifest({
    sourceRoot: "D:\\ComicSource",
    runtimePaths: runtimePaths(),
  });

  assert.equal(manifest.mode, "copy-only");
  assert.deepEqual(manifest.entries.map((entry) => entry.id), ["novels", "projects", "output", "workflows"]);
  assert.ok(manifest.entries.every((entry) => entry.action === "copy" && entry.followSymlinks === false));
  assert.equal(manifest.entries[0].sourcePath, "D:\\ComicSource\\novels");
  assert.equal(manifest.entries[1].destinationPath, runtimePaths().projectsDirectory);
  assert.equal(manifest.entries[3].destinationPath, `${runtimePaths().runtimeDirectory}\\workflows`);
  assert.ok(manifest.entries.every((entry) => !/[\\/](config|logs|backups)([\\/]|$)/i.test(entry.sourcePath)));
});

test("backup source validation checks existence and canonical containment", async () => {
  const manifest = buildMigrationManifest({ sourceRoot: "D:\\ComicSource", runtimePaths: runtimePaths() });
  const validation = await validateBackupSources(manifest, {
    lstat: async () => directoryInfo(),
    realpath: async (value) => value,
  });

  assert.equal(validation.ok, true);
  assert.equal(validation.entries.length, 4);

  await assert.rejects(
    validateBackupSources(manifest, {
      lstat: async (value) => {
        if (value.endsWith("\\output")) throw Object.assign(new Error("missing"), { code: "ENOENT" });
        return directoryInfo();
      },
      realpath: async (value) => value,
    }),
    /source for output is unavailable/,
  );
});

test("backup source validation rejects destructive, escaping, overlapping and symlink entries", async () => {
  const dependencies = { lstat: async () => directoryInfo(), realpath: async (value) => value };
  const base = {
    mode: "copy-only",
    sourceRoot: "D:\\ComicSource",
  };

  await assert.rejects(validateBackupSources({
    ...base,
    entries: [{ id: "bad", action: "move", kind: "directory", sourcePath: "D:\\ComicSource\\novels", destinationPath: "C:\\Target" }],
  }, dependencies), /only contain copy actions/);
  await assert.rejects(validateBackupSources({
    ...base,
    entries: [{ id: "bad", action: "copy", kind: "unknown", sourcePath: "D:\\ComicSource\\novels", destinationPath: "C:\\Target" }],
  }, dependencies), /invalid kind/);
  await assert.rejects(validateBackupSources({
    ...base,
    entries: [{ id: "bad", action: "copy", kind: "directory", sourcePath: "D:\\Secrets", destinationPath: "C:\\Target" }],
  }, dependencies), /escapes its allowed root/);
  await assert.rejects(validateBackupSources({
    ...base,
    entries: [{ id: "bad", action: "copy", kind: "directory", sourcePath: "D:\\ComicSource\\output", destinationPath: "D:\\ComicSource\\output\\backup" }],
  }, dependencies), /source and destination overlap/);
  await assert.rejects(validateBackupSources({
    ...base,
    entries: [{ id: "bad", action: "copy", kind: "directory", sourcePath: "D:\\ComicSource\\novels", destinationPath: "C:\\Target" }],
  }, { lstat: async (value) => value.endsWith("\\novels") ? directoryInfo({ symlink: true }) : directoryInfo(), realpath: async (value) => value }), /must not be a symbolic link/);
  await assert.rejects(validateBackupSources({
    ...base,
    entries: [{ id: "bad", action: "copy", kind: "directory", sourcePath: "D:\\ComicSource\\novels", destinationPath: "C:\\Target" }],
  }, { lstat: async () => directoryInfo(), realpath: async (value) => value.endsWith("\\novels") ? "D:\\Elsewhere\\novels" : value }), /resolves outside its allowed root/);
});

test("sha256File hashes an injected byte stream without exposing its contents", async () => {
  const digest = await sha256File("virtual.bin", {
    createReadStream: () => Readable.from([Buffer.from("abc")]),
  });

  assert.equal(digest, "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
});

test("database count reconciliation reports matches, deltas and missing objects", () => {
  const result = reconcileDatabaseObjectCounts(
    { comic_app_settings: 0, comic_projects: 2, comic_chapters: 20, comic_reviews: 4 },
    { comic_app_settings: 0, comic_projects: 2, comic_chapters: 19 },
    ["comic_app_settings", "comic_projects", "comic_chapters", "comic_reviews"],
  );

  assert.equal(result.ok, false);
  assert.equal(result.sourceTotal, 26);
  assert.equal(result.targetTotal, 21);
  assert.deepEqual(result.differences, [
    { object: "comic_chapters", source: 20, target: 19, delta: -1, status: "mismatch" },
    { object: "comic_reviews", source: 4, target: null, delta: null, status: "missing_target" },
  ]);
  assert.equal(reconcileDatabaseObjectCounts({ item: 0 }, { item: 0 }, ["item"]).ok, true);
  assert.throws(() => reconcileDatabaseObjectCounts({ item: -1 }, { item: 0 }, ["item"]), /non-negative safe integer/);
});
