const INCIDENT_KEY = "neezy-executor-incident-v1";
const MAX_STATUS_BYTES = 1_000_000;

function environmentNumber(value, fallback) {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

export function statusIssues(document, now = new Date(), maxHeartbeatSeconds = 180) {
  if (!document || typeof document !== "object") {
    return ["status response is not a JSON object"];
  }
  const issues = [];
  const heartbeat = Date.parse(document.heartbeat_utc || "");
  if (!Number.isFinite(heartbeat)) {
    issues.push("executor heartbeat is missing or invalid");
  } else {
    const age = (now.getTime() - heartbeat) / 1000;
    if (age > maxHeartbeatSeconds || age < -60) {
      issues.push(`executor heartbeat is stale (${Math.round(age)} seconds)`);
    }
  }
  if (!document.broker || document.broker.connected !== true) {
    issues.push("MT5 broker connection is offline");
  }
  const risk = document.risk || {};
  const loss = Number(risk.daily_loss_percent);
  const limit = Number(risk.daily_loss_limit_percent);
  if (Number.isFinite(loss) && Number.isFinite(limit) && loss >= limit) {
    issues.push(`maximum daily loss reached (${loss.toFixed(2)}%)`);
  }
  if (Array.isArray(risk.unprotected_bot_positions) && risk.unprotected_bot_positions.length) {
    issues.push("a bot-owned position has no broker-side stop loss");
  }
  if (document.execution && document.execution.enabled === true && risk.can_trade === false) {
    for (const blocker of Array.isArray(risk.blockers) ? risk.blockers : []) {
      issues.push(`execution blocked: ${String(blocker).slice(0, 160)}`);
    }
  }
  for (const issue of Array.isArray(document.issues) ? document.issues : []) {
    if (issue && issue.severity === "critical" && issue.message) {
      issues.push(String(issue.message).slice(0, 240));
    }
  }
  return [...new Set(issues)];
}

async function sendTelegram(env, text) {
  if (!env.ALERT_TELEGRAM_BOT_TOKEN || !env.ALERT_TELEGRAM_CHAT_ID) return false;
  const response = await fetch(
    `https://api.telegram.org/bot${env.ALERT_TELEGRAM_BOT_TOKEN}/sendMessage`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        chat_id: env.ALERT_TELEGRAM_CHAT_ID,
        text: text.slice(0, 3500),
        disable_web_page_preview: true,
      }),
      signal: AbortSignal.timeout(10_000),
    },
  );
  if (!response.ok) throw new Error("Telegram alert failed");
  return true;
}

async function sendWebhook(env, text) {
  if (!env.ALERT_WEBHOOK_URL) return false;
  const url = new URL(env.ALERT_WEBHOOK_URL);
  if (url.protocol !== "https:") throw new Error("alert webhook must use HTTPS");
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title: "NEEZY executor alert", text, source: "cloudflare-cron" }),
    signal: AbortSignal.timeout(10_000),
  });
  if (!response.ok) throw new Error("webhook alert failed");
  return true;
}

async function alert(env, text) {
  const telegramConfigured = env.ALERT_TELEGRAM_BOT_TOKEN && env.ALERT_TELEGRAM_CHAT_ID;
  if (!telegramConfigured && !env.ALERT_WEBHOOK_URL) return true;
  const results = await Promise.allSettled([sendTelegram(env, text), sendWebhook(env, text)]);
  for (const result of results) {
    if (result.status === "rejected") console.error("NEEZY alert delivery failed");
  }
  return results.some((result) => result.status === "fulfilled" && result.value === true);
}

async function archive(env, body, now) {
  if (!env.NEEZY_LOGS) return false;
  const options = { httpMetadata: { contentType: "application/json" } };
  await env.NEEZY_LOGS.put("status/latest.json", body, options);
  if (now.getUTCMinutes() < 5) {
    const key = `status/${now.toISOString().slice(0, 13).replace("T", "/")}.json`;
    await env.NEEZY_LOGS.put(key, body, options);
  }
  return true;
}

export async function checkExecutor(env, now = new Date()) {
  let body;
  let document;
  let issues;
  try {
    const url = new URL(env.NEEZY_STATUS_URL);
    if (url.protocol !== "https:") throw new Error("status URL must use HTTPS");
    const response = await fetch(url, {
      headers: {
        "CF-Access-Client-Id": env.CF_ACCESS_CLIENT_ID || "",
        "CF-Access-Client-Secret": env.CF_ACCESS_CLIENT_SECRET || "",
        Accept: "application/json",
        "User-Agent": "NEEZY-watchdog/1.0",
      },
      cf: { cacheTtl: 0 },
      signal: AbortSignal.timeout(10_000),
    });
    if (!response.ok) throw new Error(`status returned HTTP ${response.status}`);
    body = await response.text();
    if (body.length > MAX_STATUS_BYTES) throw new Error("status response is too large");
    document = JSON.parse(body);
    issues = statusIssues(document, now, environmentNumber(env.MAX_HEARTBEAT_SECONDS, 180));
  } catch (_error) {
    issues = ["status API request failed, timed out, or returned invalid JSON"];
    document = {
      schema: 1,
      service: "neezy-cloudflare-watchdog",
      status: "critical",
      observed_at: now.toISOString(),
      issues: [{ severity: "critical", message: issues[0] }],
    };
    body = JSON.stringify(document);
  }

  let previous = null;
  if (env.NEEZY_STATE) {
    try {
      previous = await env.NEEZY_STATE.get(INCIDENT_KEY, { type: "json" });
    } catch (_error) {
      console.error("NEEZY incident state could not be read");
    }
  }
  const fingerprint = issues.join("|");
  let alerted = false;
  let recovered = false;
  if (issues.length) {
    const alreadyNotified =
      previous?.fingerprint === fingerprint && previous?.notified === true;
    let delivered = alreadyNotified;
    if (!alreadyNotified) {
      delivered = await alert(
        env,
        `⚠️ NEEZY executor incident\n${issues.map((issue) => `• ${issue}`).join("\n")}`,
      );
      alerted = true;
    }
    if (env.NEEZY_STATE) {
      try {
        await env.NEEZY_STATE.put(
          INCIDENT_KEY,
          JSON.stringify({
            fingerprint,
            issues,
            notified: delivered,
            since: previous?.since || now.toISOString(),
          }),
          { expirationTtl: 604800 },
        );
      } catch (_error) {
        console.error("NEEZY incident state could not be written");
      }
    }
  } else {
    if (previous) {
      await alert(env, "✅ NEEZY executor recovered: heartbeat, broker, and risk checks are healthy.");
      recovered = true;
    }
    if (env.NEEZY_STATE) {
      try {
        await env.NEEZY_STATE.delete(INCIDENT_KEY);
      } catch (_error) {
        console.error("NEEZY incident state could not be cleared");
      }
    }
  }

  let archived = false;
  try {
    archived = await archive(env, body, now);
  } catch (_error) {
    console.error("NEEZY R2 status archive failed");
  }
  return { ok: issues.length === 0, issues, alerted, recovered, archived };
}

export default {
  scheduled(_event, env, context) {
    context.waitUntil(checkExecutor(env));
  },
  async fetch() {
    // Cron-only: anonymous HTTP requests must not trigger alerts or R2 writes.
    return new Response("Not found", { status: 404 });
  },
};
