const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");

const DEFAULT_MIGRATION_ITEMS = Object.freeze([
  Object.freeze({ id: "novels", kind: "directory", sourceRelative: "novels", destinationKey: "novelsDirectory" }),
  Object.freeze({ id: "projects", kind: "directory", sourceRelative: "manifests", destinationKey: "projectsDirectory" }),
  Object.freeze({ id: "output", kind: "directory", sourceRelative: "output", destinationKey: "outputDirectory" }),
  Object.freeze({ id: "workflows", kind: "directory", sourceRelative: "workflows", destinationKey: "runtimeDirectory", destinationRelative: "workflows" }),
]);

const DATABASE_OBJECTS = Object.freeze([
  "comic_app_settings",
  "comic_projects",
  "comic_chapters",
  "comic_episodes",
  "comic_episode_approvals",
  "comic_jobs",
  "comic_setting_items",
  "comic_visual_assets",
  "comic_chapter_breakdowns",
  "comic_generated_outputs",
  "comic_output_versions",
  "comic_reviews",
]);

function requireAbsolutePath(value, label, pathModule) {
  if (typeof value !== "string" || !value.trim() || !pathModule.isAbsolute(value)) {
    throw new TypeError(`${label} must be an absolute path`);
  }
  return pathModule.normalize(value);
}

function isPathWithin(root, candidate, pathModule) {
  const relative = pathModule.relative(root, candidate);
  return relative === "" || (!pathModule.isAbsolute(relative) && relative !== ".." && !relative.startsWith(`..${pathModule.sep}`));
}

function resolveChild(root, relativePath, label, pathModule) {
  if (typeof relativePath !== "string" || !relativePath.trim() || pathModule.isAbsolute(relativePath)) {
    throw new TypeError(`${label} must be a non-empty relative path`);
  }
  const resolved = pathModule.resolve(root, relativePath);
  if (resolved === root || !isPathWithin(root, resolved, pathModule)) {
    throw new RangeError(`${label} escapes its allowed root`);
  }
  return resolved;
}

function buildMigrationManifest(options) {
  if (!options || typeof options !== "object") throw new TypeError("options are required");
  const pathModule = options.pathModule ?? path.win32;
  const sourceRoot = requireAbsolutePath(options.sourceRoot, "sourceRoot", pathModule);
  const runtimePaths = options.runtimePaths;
  if (!runtimePaths || typeof runtimePaths !== "object") throw new TypeError("runtimePaths are required");
  const entries = DEFAULT_MIGRATION_ITEMS.map((item) => {
    const destinationRoot = requireAbsolutePath(runtimePaths[item.destinationKey], `runtimePaths.${item.destinationKey}`, pathModule);
    const destinationPath = item.destinationRelative
      ? resolveChild(destinationRoot, item.destinationRelative, `destination for ${item.id}`, pathModule)
      : destinationRoot;
    return Object.freeze({
      id: item.id,
      action: "copy",
      kind: item.kind,
      sourcePath: resolveChild(sourceRoot, item.sourceRelative, `source for ${item.id}`, pathModule),
      destinationPath,
      followSymlinks: false,
    });
  });

  return Object.freeze({
    version: 1,
    mode: "copy-only",
    sourceRoot,
    entries: Object.freeze(entries),
  });
}

function pathsOverlap(first, second, pathModule) {
  return isPathWithin(first, second, pathModule) || isPathWithin(second, first, pathModule);
}

async function inspectDirectory(directory, label, dependencies) {
  let info;
  try {
    info = await dependencies.lstat(directory);
  } catch (error) {
    throw new Error(`${label} is unavailable`, { cause: error });
  }
  if (info.isSymbolicLink()) throw new Error(`${label} must not be a symbolic link`);
  if (!info.isDirectory()) throw new Error(`${label} must be a directory`);
  return dependencies.realpath(directory);
}

async function validateBackupSources(manifest, dependencies = {}) {
  const pathModule = dependencies.pathModule ?? path.win32;
  const lstat = dependencies.lstat ?? fs.promises.lstat;
  const realpath = dependencies.realpath ?? fs.promises.realpath;
  if (!manifest || manifest.mode !== "copy-only" || !Array.isArray(manifest.entries) || manifest.entries.length === 0) {
    throw new TypeError("a copy-only migration manifest is required");
  }
  const sourceRoot = requireAbsolutePath(manifest.sourceRoot, "manifest.sourceRoot", pathModule);
  const canonicalRoot = requireAbsolutePath(
    await inspectDirectory(sourceRoot, "source root", { lstat, realpath }),
    "canonical source root",
    pathModule,
  );
  const validated = [];

  for (const entry of manifest.entries) {
    if (!entry || entry.action !== "copy") throw new Error("migration manifests may only contain copy actions");
    if (entry.kind !== "directory" && entry.kind !== "file") throw new Error(`source for ${entry.id || "entry"} has an invalid kind`);
    const sourcePath = requireAbsolutePath(entry.sourcePath, `source for ${entry.id || "entry"}`, pathModule);
    const destinationPath = requireAbsolutePath(entry.destinationPath, `destination for ${entry.id || "entry"}`, pathModule);
    if (sourcePath === sourceRoot || !isPathWithin(sourceRoot, sourcePath, pathModule)) {
      throw new RangeError(`source for ${entry.id || "entry"} escapes its allowed root`);
    }
    if (pathsOverlap(sourcePath, destinationPath, pathModule)) {
      throw new RangeError(`source and destination overlap for ${entry.id || "entry"}`);
    }

    let info;
    try {
      info = await lstat(sourcePath);
    } catch (error) {
      throw new Error(`source for ${entry.id || "entry"} is unavailable`, { cause: error });
    }
    if (info.isSymbolicLink()) throw new Error(`source for ${entry.id || "entry"} must not be a symbolic link`);
    if (entry.kind === "directory" && !info.isDirectory()) throw new Error(`source for ${entry.id || "entry"} must be a directory`);
    if (entry.kind === "file" && !info.isFile()) throw new Error(`source for ${entry.id || "entry"} must be a file`);

    const canonicalSource = requireAbsolutePath(await realpath(sourcePath), `canonical source for ${entry.id || "entry"}`, pathModule);
    if (canonicalSource === canonicalRoot || !isPathWithin(canonicalRoot, canonicalSource, pathModule)) {
      throw new RangeError(`source for ${entry.id || "entry"} resolves outside its allowed root`);
    }
    validated.push(Object.freeze({ id: entry.id, kind: entry.kind, sourcePath: canonicalSource }));
  }

  return Object.freeze({
    ok: true,
    sourceRoot: canonicalRoot,
    entries: Object.freeze(validated),
  });
}

async function sha256File(filePath, dependencies = {}) {
  if (typeof filePath !== "string" || !filePath.trim()) throw new TypeError("filePath is required");
  const createReadStream = dependencies.createReadStream ?? fs.createReadStream;
  const createHash = dependencies.createHash ?? crypto.createHash;
  const hash = createHash("sha256");
  const stream = createReadStream(filePath);
  for await (const chunk of stream) hash.update(chunk);
  return hash.digest("hex");
}

function requireCounts(value, label) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new TypeError(`${label} must be an object`);
  }
}

function requireCount(value, label) {
  if (!Number.isSafeInteger(value) || value < 0) throw new TypeError(`${label} must be a non-negative safe integer`);
  return value;
}

function reconcileDatabaseObjectCounts(sourceCounts, targetCounts, objectNames = DATABASE_OBJECTS) {
  requireCounts(sourceCounts, "sourceCounts");
  requireCounts(targetCounts, "targetCounts");
  if (!Array.isArray(objectNames) || objectNames.length === 0) throw new TypeError("objectNames must be a non-empty array");
  const names = [...new Set(objectNames)];
  if (names.some((name) => typeof name !== "string" || !name.trim())) {
    throw new TypeError("objectNames must contain non-empty strings");
  }

  let sourceTotal = 0;
  let targetTotal = 0;
  const objects = names.map((name) => {
    const hasSource = Object.prototype.hasOwnProperty.call(sourceCounts, name);
    const hasTarget = Object.prototype.hasOwnProperty.call(targetCounts, name);
    const source = hasSource ? requireCount(sourceCounts[name], `sourceCounts.${name}`) : null;
    const target = hasTarget ? requireCount(targetCounts[name], `targetCounts.${name}`) : null;
    if (source !== null) sourceTotal += source;
    if (target !== null) targetTotal += target;
    const status = !hasSource ? "missing_source" : !hasTarget ? "missing_target" : source === target ? "match" : "mismatch";
    return Object.freeze({
      object: name,
      source,
      target,
      delta: source === null || target === null ? null : target - source,
      status,
    });
  });
  const differences = objects.filter((entry) => entry.status !== "match");

  return Object.freeze({
    ok: differences.length === 0,
    checkedObjects: objects.length,
    sourceTotal,
    targetTotal,
    objects: Object.freeze(objects),
    differences: Object.freeze(differences),
  });
}

module.exports = {
  DATABASE_OBJECTS,
  DEFAULT_MIGRATION_ITEMS,
  buildMigrationManifest,
  reconcileDatabaseObjectCounts,
  sha256File,
  validateBackupSources,
};
