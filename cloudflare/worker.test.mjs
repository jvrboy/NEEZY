import test from "node:test";
import assert from "node:assert/strict";
import worker, { checkExecutor, statusIssues } from "./worker.js";

const NOW = new Date("2026-10-23T07:00:00Z");

function healthy() {
  return {
    heartbeat_utc: "2026-10-23T06:59:45Z",
    status: "ok",
    issues: [],
    broker: { connected: true },
    execution: { enabled: true },
    risk: {
      can_trade: true,
      blockers: [],
      daily_loss_percent: 0.2,
      daily_loss_limit_percent: 2,
      unprotected_bot_positions: [],
    },
  };
}

function memoryKv() {
  const values = new Map();
  return {
    values,
    async get(key, options) {
      const value = values.get(key) || null;
      return value && options?.type === "json" ? JSON.parse(value) : value;
    },
    async put(key, value) { values.set(key, value); },
    async delete(key) { values.delete(key); },
  };
}

function memoryR2() {
  const values = new Map();
  return {
    values,
    async put(key, value) { values.set(key, value); },
  };
}

function envWith(document) {
  return {
    NEEZY_STATUS_URL: "https://status.example.com/api/status",
    CF_ACCESS_CLIENT_ID: "test-id",
    CF_ACCESS_CLIENT_SECRET: "test-secret",
    NEEZY_STATE: memoryKv(),
    NEEZY_LOGS: memoryR2(),
    document,
  };
}

test("healthy status has no issues", () => {
  assert.deepEqual(statusIssues(healthy(), NOW), []);
});

test("stale heartbeat and daily loss are incidents", () => {
  const document = healthy();
  document.heartbeat_utc = "2026-10-23T06:50:00Z";
  document.risk.daily_loss_percent = 2.1;
  const issues = statusIssues(document, NOW);
  assert.ok(issues.some((issue) => issue.includes("stale")));
  assert.ok(issues.some((issue) => issue.includes("daily loss")));
});

test("unprotected positions and offline broker are incidents", () => {
  const document = healthy();
  document.broker.connected = false;
  document.risk.unprotected_bot_positions = [123];
  const issues = statusIssues(document, NOW);
  assert.ok(issues.some((issue) => issue.includes("offline")));
  assert.ok(issues.some((issue) => issue.includes("stop loss")));
});

test("identical incidents alert once and recovery clears state", async (t) => {
  const document = healthy();
  document.broker.connected = false;
  const env = envWith(document);
  t.mock.method(globalThis, "fetch", async (url, options) => {
    assert.equal(options.headers["CF-Access-Client-Id"], "test-id");
    return new Response(JSON.stringify(env.document), { status: 200 });
  });

  const first = await checkExecutor(env, NOW);
  const second = await checkExecutor(env, NOW);
  assert.equal(first.ok, false);
  assert.equal(first.alerted, true);
  assert.equal(second.alerted, false);

  env.document = healthy();
  const recovered = await checkExecutor(env, NOW);
  assert.equal(recovered.ok, true);
  assert.equal(recovered.recovered, true);
  assert.equal(env.NEEZY_STATE.values.size, 0);
});

test("R2 stores latest and an hourly snapshot", async (t) => {
  const env = envWith(healthy());
  t.mock.method(globalThis, "fetch", async () => new Response(JSON.stringify(env.document)));
  const result = await checkExecutor(env, NOW);
  assert.equal(result.archived, true);
  assert.ok(env.NEEZY_LOGS.values.has("status/latest.json"));
  assert.ok(env.NEEZY_LOGS.values.has("status/2026-10-23/07.json"));
});

test("invalid status response fails closed", async (t) => {
  const env = envWith(healthy());
  t.mock.method(globalThis, "fetch", async () => new Response("not-json", { status: 200 }));
  const result = await checkExecutor(env, NOW);
  assert.equal(result.ok, false);
  assert.match(result.issues[0], /invalid JSON/);
});

test("failed alert delivery is retried for the same incident", async (t) => {
  const document = healthy();
  document.broker.connected = false;
  const env = envWith(document);
  env.ALERT_TELEGRAM_BOT_TOKEN = "test-token";
  env.ALERT_TELEGRAM_CHAT_ID = "test-chat";
  let telegramCalls = 0;
  t.mock.method(globalThis, "fetch", async (url) => {
    if (String(url).includes("api.telegram.org")) {
      telegramCalls += 1;
      return new Response("delivery result", { status: telegramCalls === 1 ? 500 : 200 });
    }
    return new Response(JSON.stringify(env.document), { status: 200 });
  });

  await checkExecutor(env, NOW);
  await checkExecutor(env, NOW);
  await checkExecutor(env, NOW);
  assert.equal(telegramCalls, 2);
});

test("anonymous HTTP cannot trigger watchdog alerts or archives", async (t) => {
  const env = envWith(healthy());
  let fetched = false;
  t.mock.method(globalThis, "fetch", async () => {
    fetched = true;
    return new Response(JSON.stringify(env.document));
  });
  const response = await worker.fetch(new Request("https://worker.example.com/"), env);
  assert.equal(response.status, 404);
  assert.equal(fetched, false);
  assert.equal(env.NEEZY_LOGS.values.size, 0);
});
