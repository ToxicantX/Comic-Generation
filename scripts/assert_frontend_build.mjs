import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const bundlePath = resolve("console/static/vue/console-ui.js");
const bundle = readFileSync(bundlePath, "utf8");

if (bundle.includes("process.env")) {
  throw new Error(`Browser bundle contains an unresolved Node.js environment reference: ${bundlePath}`);
}

if (!bundle.includes("comicNotify")) {
  throw new Error(`Browser bundle is missing the legacy notification bridge: ${bundlePath}`);
}

if (!bundle.includes("comicDialog")) {
  throw new Error(`Browser bundle is missing the legacy dialog bridge: ${bundlePath}`);
}
