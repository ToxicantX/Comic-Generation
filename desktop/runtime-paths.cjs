const path = require("node:path");

const DEFAULT_APP_NAME = "Comic Pipeline";

function nonEmpty(value) {
  return typeof value === "string" && value.trim() ? value.trim() : "";
}

function requireAbsolutePath(value, label, pathModule) {
  const candidate = nonEmpty(value);
  if (!candidate || !pathModule.isAbsolute(candidate)) {
    throw new TypeError(`${label} must be an absolute Windows path`);
  }
  return pathModule.normalize(candidate);
}

function requireDirectoryName(value, pathModule) {
  const name = nonEmpty(value);
  if (!name || name === "." || name === ".." || /[\\/:]/.test(name) || pathModule.isAbsolute(name)) {
    throw new TypeError("appName must be a single directory name");
  }
  return name;
}

function resolveWindowsBaseDirectories(options = {}) {
  const pathModule = options.pathModule ?? path.win32;
  const env = options.env ?? process.env;
  const homeDirectory = nonEmpty(options.homeDirectory) || nonEmpty(env.USERPROFILE);
  const appDataCandidate = nonEmpty(options.appDataDirectory)
    || nonEmpty(env.APPDATA)
    || (homeDirectory ? pathModule.join(homeDirectory, "AppData", "Roaming") : "");
  const documentsCandidate = nonEmpty(options.documentsDirectory)
    || (homeDirectory ? pathModule.join(homeDirectory, "Documents") : "");

  return Object.freeze({
    homeDirectory: requireAbsolutePath(homeDirectory, "homeDirectory", pathModule),
    appDataDirectory: requireAbsolutePath(appDataCandidate, "appDataDirectory", pathModule),
    documentsDirectory: requireAbsolutePath(documentsCandidate, "documentsDirectory", pathModule),
  });
}

function buildWindowsRuntimePaths(options = {}) {
  const pathModule = options.pathModule ?? path.win32;
  const appName = requireDirectoryName(options.appName ?? DEFAULT_APP_NAME, pathModule);
  const bases = resolveWindowsBaseDirectories({ ...options, pathModule });
  const userDataRoot = pathModule.join(bases.appDataDirectory, appName);
  const databaseRoot = pathModule.join(bases.homeDirectory, ".comic-pipeline");
  const documentsRoot = pathModule.join(bases.documentsDirectory, appName);

  return Object.freeze({
    appName,
    userDataRoot,
    configDirectory: pathModule.join(userDataRoot, "config"),
    logsDirectory: pathModule.join(userDataRoot, "logs"),
    runtimeDirectory: pathModule.join(userDataRoot, "runtime"),
    databaseDirectory: pathModule.join(databaseRoot, "database"),
    backupsDirectory: pathModule.join(userDataRoot, "backups"),
    updatesDirectory: pathModule.join(userDataRoot, "updates"),
    documentsRoot,
    novelsDirectory: pathModule.join(documentsRoot, "novels"),
    projectsDirectory: pathModule.join(documentsRoot, "projects"),
    outputDirectory: pathModule.join(documentsRoot, "output"),
  });
}

module.exports = {
  DEFAULT_APP_NAME,
  buildWindowsRuntimePaths,
  resolveWindowsBaseDirectories,
};
