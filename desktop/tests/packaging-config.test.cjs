const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const YAML = require("yaml");

const root = path.resolve(__dirname, "../..");
const configPath = path.join(root, "electron-builder.yml");
const packagePath = path.join(root, "package.json");
const configText = fs.readFileSync(configPath, "utf8");
const config = YAML.parse(configText);
const packageJson = JSON.parse(fs.readFileSync(packagePath, "utf8"));

test("Windows packaging targets NSIS and portable x64 artifacts", () => {
  assert.equal(packageJson.author, "ToxicantX");
  assert.equal(config.asar, true);
  assert.deepEqual(config.win.target, [
    { target: "nsis", arch: ["x64"] },
    { target: "portable", arch: ["x64"] },
  ]);
  assert.equal(config.nsis.artifactName, "${productName}-Setup-${version}-${arch}.${ext}");
  assert.equal(config.portable.artifactName, "${productName}-Portable-${version}-${arch}.${ext}");
  assert.equal(config.win.forceCodeSigning, false);
  assert.equal(config.win.signAndEditExecutable, true);
});

test("package contents are explicitly allowlisted", () => {
  assert.deepEqual(config.files, [
    "package.json",
    "desktop/*.cjs",
    "desktop/*.html",
    "desktop/*.css",
    "desktop/*.js",
    "!desktop/tests/**",
  ]);
  assert.equal(config.files.includes("**/*"), false);
  assert.equal(packageJson.dependencies["embedded-postgres"], "16.14.0-beta.17");
  assert.match(packageJson.dependencies["electron-updater"], /^\^6\./);
  assert.equal(packageJson.devDependencies.vue, "^3.5.43");
  assert.deepEqual(config.asarUnpack, ["node_modules/**"]);
  assert.deepEqual(config.extraResources.map((entry) => entry.to), [
    "runtime/python",
    "runtime/app",
  ]);
});

test("GitHub metadata is non-secret and local builds never publish", () => {
  assert.deepEqual(config.publish, [{
    provider: "github",
    owner: "ToxicantX",
    repo: "Comic-Generation",
    releaseType: "draft",
    publishAutoUpdate: true,
  }]);
  assert.match(packageJson.scripts["desktop:dist:win"], /--publish never/);
  assert.doesNotMatch(
    configText,
    /CSC_LINK|CSC_KEY_PASSWORD|GH_TOKEN|GITHUB_TOKEN|privateKey|certificatePassword/i,
  );
});

test("NSIS uninstall preserves application user data by default", () => {
  assert.equal(config.nsis.deleteAppDataOnUninstall, false);
  assert.equal(config.nsis.oneClick, false);
  assert.equal(config.nsis.perMachine, false);
});
