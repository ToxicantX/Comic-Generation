const assert = require("node:assert/strict");
const http = require("node:http");
const test = require("node:test");
const {
  ServiceManager,
  normalizeServiceUrl,
  probeConsole,
} = require("../service-manager.cjs");

test("desktop service URL only accepts loopback HTTP", () => {
  assert.equal(normalizeServiceUrl("http://localhost:8199/path?x=1"), "http://localhost:8199");
  assert.equal(normalizeServiceUrl("http://127.0.0.1:8199"), "http://127.0.0.1:8199");
  assert.throws(() => normalizeServiceUrl("https://127.0.0.1:8199"));
  assert.throws(() => normalizeServiceUrl("http://example.com:8199"));
});

test("probeConsole requires a successful config endpoint", async (context) => {
  const server = http.createServer((request, response) => {
    response.statusCode = request.url === "/api/config" ? 200 : 404;
    response.end("{}");
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  context.after(() => server.close());
  const address = server.address();
  assert.equal(await probeConsole(`http://127.0.0.1:${address.port}`), true);
});

test("existing backend is reused without starting Docker", async () => {
  let composeCalls = 0;
  const manager = new ServiceManager({
    appRoot: "C:/comic",
    probe: async () => true,
    runCompose: async () => { composeCalls += 1; return { ok: true }; },
  });
  const result = await manager.ensureRunning();
  assert.equal(result.ok, true);
  assert.equal(result.reused, true);
  assert.equal(composeCalls, 0);
});

test("missing backend starts Compose and waits for readiness", async () => {
  let probes = 0;
  let composeCalls = 0;
  const phases = [];
  const manager = new ServiceManager({
    appRoot: "C:/comic",
    probe: async () => { probes += 1; return false; },
    runCompose: async () => { composeCalls += 1; return { ok: true, output: "started" }; },
    waitForConsole: async () => true,
  });
  const result = await manager.ensureRunning((status) => phases.push(status.phase));
  assert.equal(result.ok, true);
  assert.equal(result.reused, false);
  assert.equal(probes, 1);
  assert.equal(composeCalls, 1);
  assert.deepEqual(phases, ["checking", "starting", "waiting"]);
});

test("Compose failure returns actionable diagnostics", async () => {
  const manager = new ServiceManager({
    appRoot: "C:/comic",
    probe: async () => false,
    runCompose: async () => ({ ok: false, code: 1, output: "daemon unavailable", error: "" }),
  });
  const result = await manager.ensureRunning();
  assert.equal(result.ok, false);
  assert.equal(result.phase, "compose_failed");
  assert.match(result.message, /Docker Desktop/);
  assert.equal(result.detail, "daemon unavailable");
});
