# NEEZY read-only dashboard

Next.js 16 monitoring UI for the lightweight Windows executor. It shows restart-
persistent recent equity, open MT5 positions, validated model IDs/inference, exact-
candidate paper progress, heartbeat, and risk blocks. It has no order, promotion, or
settings mutation.

## Local production check

```bash
npm ci
npm run build
```

For development, copy `.env.example` to `.env.local`, fill real values locally, and run
`npm run dev`. The server binds `0.0.0.0` only for development previews; the PC status
API itself remains loopback-only behind Cloudflare Tunnel + Access.

## Vercel

Import this `dashboard/` directory as the project root and set:

- `NEEZY_STATUS_URL=https://status.example.com/api/status`
- `CF_ACCESS_CLIENT_ID` / `CF_ACCESS_CLIENT_SECRET`
- `DASHBOARD_USERNAME` / `DASHBOARD_PASSWORD`

The dynamic `/` page server-renders the initial snapshot, and `/api/status` is a Node
server route for refreshes. Only server code adds the Cloudflare Access service-token
headers; they are never embedded in client JavaScript. `proxy.js` requires Basic Auth
for the UI and status route and returns 503 if dashboard credentials are not configured.
Use HTTPS, a long unique password, and optionally Vercel Deployment Protection/SSO as an
additional layer. Rotate credentials through Vercel/Cloudflare, never Git.

The browser calls only its relative `/api/status` every 30 seconds. On an outage it keeps
the last good snapshot visible and shows an explicit warning. Do not point
`NEEZY_STATUS_URL` at an unauthenticated public origin.
