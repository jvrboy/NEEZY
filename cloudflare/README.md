# Cloudflare watchdog + R2 archive

`worker.js` checks the PC's read-only status endpoint every five minutes. It uses KV to
alert once per distinct incident and on recovery, and writes sanitized status/equity
JSON to R2 (`status/latest.json` plus hourly snapshots). Telegram is direct; an optional
HTTPS webhook can trigger an email automation.

## Deploy

1. Complete the Named Tunnel and Cloudflare Access setup in
   `docs/CLOUD_OPERATIONS.md` first.
2. Edit `wrangler.toml`: set `NEEZY_STATUS_URL`, create a KV namespace, and replace
   `REPLACE_WITH_KV_NAMESPACE_ID`. Create the R2 bucket named in the file.
3. From this directory:

   ```bash
   npx wrangler login
   npx wrangler kv namespace create NEEZY_STATE
   npx wrangler r2 bucket create neezy-executor-logs
   npx wrangler secret put CF_ACCESS_CLIENT_ID
   npx wrangler secret put CF_ACCESS_CLIENT_SECRET
   npx wrangler secret put ALERT_TELEGRAM_BOT_TOKEN
   npx wrangler secret put ALERT_TELEGRAM_CHAT_ID
   # Optional email automation:
   npx wrangler secret put ALERT_WEBHOOK_URL
   npx wrangler deploy
   ```

Set at least one alert destination. Do not put secret values in `wrangler.toml`. The
Worker is cron-only (`*/5 * * * *`); anonymous HTTP requests return 404 and cannot
trigger alerts or R2 writes. Failed alert deliveries are retried on the next cron run.

## Test

```bash
node --test worker.test.mjs
```

Tests use mocked fetch/KV/R2 and cover stale heartbeats, offline brokers, daily-loss and
missing-stop incidents, alert dedupe/recovery, invalid JSON, Access headers, and archives.
