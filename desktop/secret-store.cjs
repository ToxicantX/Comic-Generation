const fs = require("node:fs");
const path = require("node:path");

const SECRET_NAMES = Object.freeze(["textApiKey", "imageApiKey", "databasePassword"]);
const secretNameSet = new Set(SECRET_NAMES);

function validateSecretName(name) {
  if (typeof name !== "string" || !secretNameSet.has(name)) {
    throw new TypeError("Secret name is not approved by the desktop application.");
  }
  return name;
}

function validateSecretValue(value) {
  if (typeof value !== "string" || !value.trim()) {
    throw new TypeError("Secret value must be a non-empty string.");
  }
  if (value.length > 16384 || value.includes("\0")) {
    throw new TypeError("Secret value is invalid.");
  }
  return value;
}

function createSecretStore(options) {
  if (!options?.safeStorage || typeof options.safeStorage.isEncryptionAvailable !== "function") {
    throw new TypeError("safeStorage is required.");
  }
  const filePath = path.resolve(String(options.filePath || ""));
  if (!path.isAbsolute(filePath)) throw new TypeError("filePath must be absolute.");
  const fileSystem = options.fileSystem ?? fs;

  function requireEncryption() {
    if (!options.safeStorage.isEncryptionAvailable()) {
      throw new Error("System credential encryption is unavailable.");
    }
  }

  function readDocument() {
    if (!fileSystem.existsSync(filePath)) return { version: 1, secrets: {} };
    const parsed = JSON.parse(fileSystem.readFileSync(filePath, "utf8"));
    if (parsed?.version !== 1 || !parsed.secrets || typeof parsed.secrets !== "object" || Array.isArray(parsed.secrets)) {
      throw new Error("Desktop secret store is invalid.");
    }
    return parsed;
  }

  function writeDocument(document) {
    fileSystem.mkdirSync(path.dirname(filePath), { recursive: true });
    const temporaryPath = `${filePath}.${process.pid}.tmp`;
    fileSystem.writeFileSync(temporaryPath, `${JSON.stringify(document, null, 2)}\n`, { encoding: "utf8", mode: 0o600 });
    try {
      fileSystem.renameSync(temporaryPath, filePath);
    } catch (error) {
      if (error?.code !== "EXDEV") {
        try { fileSystem.unlinkSync?.(temporaryPath); } catch {}
        throw error;
      }
      fileSystem.copyFileSync(temporaryPath, filePath);
      fileSystem.chmodSync?.(filePath, 0o600);
      fileSystem.unlinkSync(temporaryPath);
    }
  }

  function set(name, value) {
    requireEncryption();
    const key = validateSecretName(name);
    const secret = validateSecretValue(value);
    const document = readDocument();
    document.secrets[key] = options.safeStorage.encryptString(secret).toString("base64");
    writeDocument(document);
  }

  function get(name) {
    requireEncryption();
    const key = validateSecretName(name);
    const encrypted = readDocument().secrets[key];
    if (!encrypted) return "";
    return options.safeStorage.decryptString(Buffer.from(encrypted, "base64"));
  }

  function has(name) {
    const key = validateSecretName(name);
    return Boolean(readDocument().secrets[key]);
  }

  function remove(name) {
    const key = validateSecretName(name);
    const document = readDocument();
    if (!document.secrets[key]) return false;
    delete document.secrets[key];
    writeDocument(document);
    return true;
  }

  return Object.freeze({ filePath, get, has, remove, set });
}

module.exports = {
  SECRET_NAMES,
  createSecretStore,
  validateSecretName,
  validateSecretValue,
};
