const assert = require("node:assert/strict");
const test = require("node:test");
const {
  buildWindowsRuntimePaths,
  resolveWindowsBaseDirectories,
} = require("../runtime-paths.cjs");

test("buildWindowsRuntimePaths creates the documented roaming and documents layout", () => {
  const paths = buildWindowsRuntimePaths({
    env: {
      APPDATA: "C:\\Users\\Ada\\AppData\\Roaming",
      USERPROFILE: "C:\\Users\\Ada",
    },
  });

  assert.equal(paths.userDataRoot, "C:\\Users\\Ada\\AppData\\Roaming\\Comic Pipeline");
  assert.equal(paths.configDirectory, `${paths.userDataRoot}\\config`);
  assert.equal(paths.logsDirectory, `${paths.userDataRoot}\\logs`);
  assert.equal(paths.runtimeDirectory, `${paths.userDataRoot}\\runtime`);
  assert.equal(paths.databaseDirectory, "C:\\Users\\Ada\\.comic-pipeline\\database");
  assert.equal(paths.backupsDirectory, `${paths.userDataRoot}\\backups`);
  assert.equal(paths.updatesDirectory, `${paths.userDataRoot}\\updates`);
  assert.equal(paths.documentsRoot, "C:\\Users\\Ada\\Documents\\Comic Pipeline");
  assert.equal(paths.novelsDirectory, `${paths.documentsRoot}\\novels`);
  assert.equal(paths.projectsDirectory, `${paths.documentsRoot}\\projects`);
  assert.equal(paths.outputDirectory, `${paths.documentsRoot}\\output`);
});

test("base directories support redirected Documents and APPDATA fallback", () => {
  const redirected = resolveWindowsBaseDirectories({
    env: {},
    homeDirectory: "D:\\Profiles\\Writer",
    documentsDirectory: "E:\\Library",
  });

  assert.deepEqual(redirected, {
    homeDirectory: "D:\\Profiles\\Writer",
    appDataDirectory: "D:\\Profiles\\Writer\\AppData\\Roaming",
    documentsDirectory: "E:\\Library",
  });
});

test("runtime paths reject relative roots and app names that can escape", () => {
  assert.throws(
    () => buildWindowsRuntimePaths({ env: { APPDATA: "relative", USERPROFILE: "C:\\Users\\Ada" } }),
    /appDataDirectory must be an absolute Windows path/,
  );
  assert.throws(
    () => buildWindowsRuntimePaths({ env: { APPDATA: "C:\\Data", USERPROFILE: "C:\\Users\\Ada" }, appName: "..\\Other" }),
    /appName must be a single directory name/,
  );
  assert.throws(
    () => resolveWindowsBaseDirectories({ env: {} }),
    /homeDirectory must be an absolute Windows path/,
  );
});
