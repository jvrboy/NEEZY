import test from "node:test";
import assert from "node:assert/strict";
import { fetchExecutorResource, MAX_RESPONSE_BYTES } from "../lib/executor.mjs";
import { parsePreferenceBundle, preferenceBundle } from "../lib/preferences.mjs";
import { parseResearchReport } from "../lib/research-report.mjs";
import { filterPositions } from "../lib/positions.mjs";
import { normalizeSnapshot, heartbeatAge } from "../lib/snapshot.mjs";

const env = { NEEZY_STATUS_URL: "https://executor.example/api/status", CF_ACCESS_CLIENT_SECRET: "test-only" };
test("executor transport restricts resources, HTTPS and redirects", async () => {
  await assert.rejects(fetchExecutorResource("orders", { env }));
  await assert.rejects(fetchExecutorResource("status", { env: { NEEZY_STATUS_URL: "http://localhost/api/status" } }));
  await assert.rejects(fetchExecutorResource("status", { env: { NEEZY_STATUS_URL: "https://name:password@example.test" } }));
  let captured;
  const doc = await fetchExecutorResource("insights", { env, fetcher: async (url, options) => { captured = { url, options }; return Response.json({ schema: 1 }); } });
  assert.equal(doc.schema, 1); assert.equal(captured.url.pathname, "/api/insights");
  assert.equal(captured.options.redirect, "error");
  assert.equal(captured.options.headers["CF-Access-Client-Secret"], "test-only");
});
test("executor transport bounds streamed bytes and rejects invalid documents", async () => {
  const large = () => new Response("x".repeat(MAX_RESPONSE_BYTES + 1), { headers: { "Content-Type": "application/json" } });
  await assert.rejects(fetchExecutorResource("status", { env, fetcher: large }), /too large/);
  for (const doc of [[], null, 1]) await assert.rejects(fetchExecutorResource("status", { env, fetcher: () => Response.json(doc) }));
  await assert.rejects(fetchExecutorResource("status", { env, fetcher: () => new Response("<html>not JSON</html>") }), /content type/);
});
test("portable preferences contain no arbitrary account or secret fields", () => {
  const bundle = preferenceBundle({ theme: "contrast", apiKey: "secret", execution: true });
  assert.equal(parsePreferenceBundle(JSON.stringify(bundle)).theme, "contrast");
  assert.equal(JSON.stringify(bundle).includes("secret"), false);
  assert.throws(() => parsePreferenceBundle('{"schema":2}'));
  assert.throws(() => parsePreferenceBundle("x".repeat(10001)));
});
test("position filters are deterministic and do not mutate the snapshot", () => {
  const positions = [{ ticket: 1, symbol: "EURUSD", type: "BUY", profit: 5 }, { ticket: 2, symbol: "USDJPY", type: "SELL", profit: -3 }];
  assert.equal(filterPositions(positions, { query: "eur", side: "buy" }).length, 1);
  assert.equal(filterPositions(positions, { sort: "profit" })[0].ticket, 1);
  assert.equal(positions[0].ticket, 1);
});
test("snapshot normalization prevents malformed collection crashes and stale ages advance", () => {
  const doc = normalizeSnapshot({ status: "ok", models: { bad: null, good: { active: true } }, open_trades: [null], equity_history: [null, { equity: null }], heartbeat_age_seconds: 2 });
  assert.equal(Object.keys(doc.models).length, 1); assert.equal(doc.open_trades.length, 0); assert.equal(doc.equity_history.length, 0);
  assert.equal(heartbeatAge(doc, 1000, 61000), 62);
  assert.equal(heartbeatAge({ heartbeat_age_seconds: null }, 0, 0), null);
});
test("research viewer accepts only bounded advisory indicator reports", () => {
  const report = { schema: 1, engine: "fras", indicator: "FRAS", symbol: "EURUSD", advisory_only: true, bars: 1, latest: { epoch: 10, ready: false, values: { score: null } } };
  assert.equal(parseResearchReport(JSON.stringify(report)).engine, "fras");
  assert.throws(() => parseResearchReport(JSON.stringify({ ...report, advisory_only: false })));
  assert.throws(() => parseResearchReport(JSON.stringify({ ...report, series: [] })));
  assert.throws(() => parseResearchReport("x".repeat(5000001)));
});
