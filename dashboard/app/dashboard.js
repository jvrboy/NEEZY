"use client";

import { useEffect, useMemo, useState } from "react";
import ResearchLibrary from "./components/research-library";
import WorkspaceSettings from "./components/workspace-settings";
import { DEFAULT_PREFERENCES, STORAGE_KEY, sanitizePreferences } from "../lib/preferences.mjs";

function number(value, digits = 2) {
  if (value === null || value === undefined || value === "") return "—";
  const parsed = Number(value);
  return Number.isFinite(parsed)
    ? parsed.toLocaleString(undefined, {
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
      })
    : "—";
}

function stamp(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString();
}

function epoch(value) {
  return value ? stamp(Number(value) * 1000) : "—";
}

function EquityChart({ samples }) {
  const chart = useMemo(() => {
    const values = (Array.isArray(samples) ? samples : [])
      .map((sample) => ({ time: sample.time, value: Number(sample.equity) }))
      .filter((sample) => Number.isFinite(sample.value));
    if (values.length < 2) return null;
    const raw = values.map((sample) => sample.value);
    const minimum = Math.min(...raw);
    const maximum = Math.max(...raw);
    const padding = Math.max((maximum - minimum) * 0.12, maximum * 0.0001, 0.01);
    const low = minimum - padding;
    const high = maximum + padding;
    const points = values.map((sample, index) => ({
      ...sample,
      x: (index / (values.length - 1)) * 600,
      y: 158 - ((sample.value - low) / (high - low)) * 138,
    }));
    return {
      points,
      minimum,
      maximum,
      line: points.map((point) => `${point.x},${point.y}`).join(" "),
      area: `0,170 ${points.map((point) => `${point.x},${point.y}`).join(" ")} 600,170`,
      first: values[0].time,
      last: values.at(-1).time,
    };
  }, [samples]);

  if (!chart) {
    return <div className="chart-empty">Equity samples appear after the first broker reads.</div>;
  }
  return (
    <div className="chart-wrap">
      <div className="chart-labels">
        <span>High {number(chart.maximum)}</span>
        <span>Low {number(chart.minimum)}</span>
      </div>
      <svg viewBox="0 0 600 180" role="img" aria-label="Recent account equity">
        <defs>
          <linearGradient id="equity-fill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#49e5ad" stopOpacity="0.24" />
            <stop offset="100%" stopColor="#49e5ad" stopOpacity="0" />
          </linearGradient>
        </defs>
        <line x1="0" y1="158" x2="600" y2="158" className="chart-axis" />
        <polygon points={chart.area} fill="url(#equity-fill)" />
        <polyline points={chart.line} className="equity-line" />
        <circle cx={chart.points.at(-1).x} cy={chart.points.at(-1).y} r="4" className="chart-dot" />
      </svg>
      <div className="chart-times">
        <span>{stamp(chart.first)}</span>
        <span>{stamp(chart.last)}</span>
      </div>
    </div>
  );
}

function Metric({ label, value, detail, tone = "" }) {
  return (
    <section className="metric">
      <span className="metric-label">{label}</span>
      <strong className={tone}>{value}</strong>
      <span className="metric-detail">{detail}</span>
    </section>
  );
}

export default function Dashboard({ initialStatus = null, initialError = "" }) {
  const [tab, setTab] = useState("overview");
  const [preferences, setPreferences] = useState(DEFAULT_PREFERENCES);
  const [preferencesReady, setPreferencesReady] = useState(false);
  const [paused, setPaused] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  useEffect(() => {
    try { setPreferences(sanitizePreferences(JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}"))); } catch (_) { /* restricted or corrupt browser storage */ }
    setPreferencesReady(true);
  }, []);
  useEffect(() => {
    document.documentElement.dataset.theme = preferences.theme;
    document.documentElement.dataset.density = preferences.density;
    document.documentElement.dataset.reducedMotion = String(preferences.reducedMotion);
    if (preferencesReady) {
      try { localStorage.setItem(STORAGE_KEY, JSON.stringify(preferences)); } catch (_) { /* private browsing */ }
    }
  }, [preferences, preferencesReady]);
  const [status, setStatus] = useState(initialStatus);
  const [error, setError] = useState(initialError);
  const [updated, setUpdated] = useState(null);

  useEffect(() => {
    if (!preferencesReady || paused) return;
    let active = true;
    let controller;
    async function refresh() {
      controller?.abort();
      controller = new AbortController();
      try {
        const response = await fetch("/api/status", {
          cache: "no-store",
          signal: controller.signal,
        });
        const document = await response.json();
        if (!response.ok) throw new Error(document.error || "Status unavailable");
        if (active) {
          setStatus(document);
          setUpdated(new Date());
          setError("");
        }
      } catch (reason) {
        if (active && reason.name !== "AbortError") {
          setError("Live status is unavailable. Showing the last successful snapshot.");
        }
      }
    }
    refresh();
    const interval = setInterval(() => { if (!document.hidden) refresh(); }, preferences.refreshSeconds * 1000);
    return () => {
      active = false;
      controller?.abort();
      clearInterval(interval);
    };
  }, [preferencesReady, paused, preferences.refreshSeconds, refreshKey]);

  const account = status?.account || {};
  const risk = status?.risk || {};
  const broker = status?.broker || {};
  const execution = status?.execution || {};
  const paper = status?.paper_validation;
  const trades = Array.isArray(status?.open_trades) ? status.open_trades : [];
  const models = Object.entries(status?.models || {});
  const activeModels = models.filter(([, model]) => model.active).length;
  const state = status?.status || "loading";
  const pnl = Number(risk.daily_pnl);
  const heartbeat = Number(status?.heartbeat_age_seconds);

  return (
    <main>
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">N</span>
          <div>
            <h1>NEEZY <span>Executor</span></h1>
            <p>Light PC execution · cloud intelligence</p>
          </div>
        </div>
        <div className="topbar-right">
          <span className="mode-badge">
            {execution.mode === "paper-validation"
              ? "PAPER VALIDATION"
              : execution.enabled
                ? "DEMO EXECUTION"
                : "OBSERVE ONLY"}
          </span>
          <div className={`state-pill ${state}`}>
            <span className="pulse" /> {state.toUpperCase()}
          </div>
        </div>
      </header>

      <nav className="workspace-nav" aria-label="Workspace">
        <div className="nav-tabs">{[["overview", "Overview"], ["library", "Research library"], ["settings", "Settings"]].map(([id, label]) => <button key={id} type="button" aria-pressed={tab === id} className={tab === id ? "active" : ""} onClick={() => setTab(id)}>{label}</button>)}</div>
        <div className="nav-actions"><button type="button" onClick={() => setPaused(!paused)}>{paused ? "Resume updates" : "Pause updates"}</button><button type="button" disabled={paused} onClick={() => setRefreshKey((value) => value + 1)}>Refresh now</button></div>
      </nav>
      {Number.isFinite(heartbeat) && heartbeat > preferences.staleSeconds && <div className="error-banner" role="status">Stale executor heartbeat. Treat displayed data as historical; do not rely on it for execution decisions.</div>}
      {paused && <p className="warning" role="status">Updates paused. The current snapshot is not live.</p>}
      {error && <div className="error-banner" role="status">{error}</div>}
      {tab === "library" && <ResearchLibrary />}
      {tab === "settings" && <WorkspaceSettings preferences={preferences} onChange={(value) => setPreferences(sanitizePreferences(value))} />}
      {tab === "overview" && <>
      {!status && !error && <div className="loading">Connecting to the executor…</div>}

      <section className="metrics-grid">
        <Metric
          label="Account equity"
          value={`${number(account.equity)} ${account.currency || ""}`}
          detail={`Balance ${number(account.balance)} · ${account.trade_mode || "unknown"}`}
        />
        <Metric
          label="Daily P / L"
          value={`${Number.isFinite(pnl) && pnl > 0 ? "+" : ""}${number(risk.daily_pnl)}`}
          detail={`${number(risk.daily_loss_percent)}% of ${number(risk.daily_loss_limit_percent)}% loss limit`}
          tone={pnl > 0 ? "positive" : pnl < 0 ? "negative" : ""}
        />
        <Metric
          label="Open risk"
          value={`${trades.length} position${trades.length === 1 ? "" : "s"}`}
          detail={`${number(risk.trades_today, 0)} / ${number(risk.daily_trade_limit, 0)} orders today`}
        />
        <Metric
          label="Validated models"
          value={`${activeModels} / ${models.length}`}
          detail={`${status?.timeframe || "—"} · checked on the PC`}
        />
      </section>

      <div className="primary-grid">
        <section className="panel equity-panel">
          <div className="panel-heading">
            <div>
              <span className="eyebrow">PERFORMANCE</span>
              <h2>Recent equity</h2>
            </div>
            <span className="subtle">Rolling PC samples</span>
          </div>
          <EquityChart samples={status?.equity_history} />
        </section>

        <section className="panel health-panel">
          <div className="panel-heading">
            <div>
              <span className="eyebrow">SYSTEM</span>
              <h2>Execution health</h2>
            </div>
          </div>
          <dl className="health-list">
            <div><dt>Broker</dt><dd className={broker.connected ? "positive" : "negative"}>
              {broker.connected ? "MT5 connected" : "Offline"}
            </dd></div>
            <div><dt>Heartbeat</dt><dd>{Number.isFinite(heartbeat) ? `${number(heartbeat, 0)}s ago` : "—"}</dd></div>
            <div><dt>Last heartbeat UTC</dt><dd>{stamp(status?.heartbeat_utc)}</dd></div>
            <div><dt>Risk gate</dt><dd className={risk.can_trade ? "positive" : "warning"}>
              {risk.can_trade ? "Open" : "Blocked"}
            </dd></div>
            <div><dt>Last dashboard refresh</dt><dd>{updated ? updated.toLocaleTimeString() : "—"}</dd></div>
          </dl>
          {!!risk.blockers?.length && (
            <div className="blockers">
              {risk.blockers.map((blocker) => <span key={blocker}>{blocker}</span>)}
            </div>
          )}
        </section>
      </div>

      <section className="panel">
        <div className="panel-heading">
          <div>
            <span className="eyebrow">BROKER POSITIONS</span>
            <h2>Open trades</h2>
          </div>
          <span className="subtle">Read-only · broker-side SL/TP</span>
        </div>
        <div className="table-scroll">
          <table>
            <thead><tr>
              <th>Ticket</th><th>Market</th><th>Side</th><th>Size</th><th>Entry</th><th>Stop loss</th><th>Take profit</th><th className="align-right">P / L</th>
            </tr></thead>
            <tbody>
              {trades.map((trade) => (
                <tr key={trade.ticket}>
                  <td className="muted">#{trade.ticket}</td>
                  <td><strong>{trade.symbol}</strong></td>
                  <td><span className={`side ${String(trade.type).toLowerCase()}`}>{trade.type}</span></td>
                  <td>{number(trade.volume)}</td>
                  <td>{number(trade.price_open, 5)}</td>
                  <td>{number(trade.sl, 5)}</td>
                  <td>{number(trade.tp, 5)}</td>
                  <td className={`align-right ${Number(trade.profit) >= 0 ? "positive" : "negative"}`}>
                    {number(trade.profit)}
                  </td>
                </tr>
              ))}
              {!trades.length && <tr><td colSpan="8" className="empty">No open positions reported.</td></tr>}
            </tbody>
          </table>
        </div>
      </section>

      {paper && (
        <section className="panel">
          <div className="panel-heading">
            <div>
              <span className="eyebrow">EXACT-HASH VALIDATION</span>
              <h2>Paper candidate</h2>
            </div>
            <span className="subtle">Virtual trades only · no broker orders</span>
          </div>
          <div className="model-grid">
            <article className="model-card">
              <div className="model-title">
                <strong>{paper.symbol || "Candidate"}</strong>
                <span className={paper.passed ? "model-active" : "model-inactive"}>
                  {String(paper.status || "loading").replaceAll("_", " ").toUpperCase()}
                </span>
              </div>
              <code>{paper.model_id || "Downloading validated candidate"}</code>
              {paper.error ? (
                <p>{paper.error}</p>
              ) : (
                <dl>
                  <div><dt>Closed virtual trades</dt><dd>
                    {number(paper.trades, 0)} / {number(paper.minimum_trades, 0)}
                  </dd></div>
                  <div><dt>Full validation days</dt><dd>
                    {number(paper.days, 0)} / {number(paper.minimum_days, 0)}
                  </dd></div>
                  <div><dt>Expectancy</dt><dd>{number(paper.expectancy_r, 3)} R</dd></div>
                  <div><dt>Open simulation</dt><dd>{paper.open_simulation ? "Yes" : "No"}</dd></div>
                  <div><dt>Spread assumption</dt><dd>{paper.spread ?? "—"}</dd></div>
                </dl>
              )}
              {paper.passed && (
                <small className="positive">Eligible for deliberate promotion review.</small>
              )}
            </article>
          </div>
        </section>
      )}

      <section className="panel">
        <div className="panel-heading">
          <div>
            <span className="eyebrow">HUGGING FACE REGISTRY</span>
            <h2>Models & latest inference</h2>
          </div>
          <span className="subtle">Hash + backtest + paper validated</span>
        </div>
        <div className="model-grid">
          {models.map(([symbol, model]) => (
            <article className="model-card" key={symbol}>
              <div className="model-title">
                <strong>{symbol}</strong>
                <span className={model.active ? "model-active" : "model-inactive"}>
                  {model.active ? "ACTIVE" : "WAITING"}
                </span>
              </div>
              <code>{model.model_id || "No promoted model"}</code>
              {model.last_prediction ? (
                <dl>
                  <div><dt>Signal</dt><dd>{model.last_prediction.direction || model.last_prediction.status}</dd></div>
                  <div><dt>Up probability</dt><dd>{model.last_prediction.up_probability ?? "—"}</dd></div>
                  <div><dt>Closed candle</dt><dd>{epoch(model.last_prediction.closed_epoch)}</dd></div>
                </dl>
              ) : <p>No inference on this service yet.</p>}
              {model.update?.status && <small>Updater: {model.update.status}</small>}
            </article>
          ))}
          {!models.length && <div className="empty">No model registry configured.</div>}
        </div>
      </section>

      {!!status?.issues?.length && (
        <section className="panel incidents">
          <span className="eyebrow">CURRENT NOTICES</span>
          {status.issues.map((issue, index) => (
            <p key={`${issue.code}-${index}`}><strong>{issue.severity}</strong> {issue.message}</p>
          ))}
        </section>
      )}

      </>}
      <footer>
        <span>NEEZY read-only monitoring</span>
        <span>Training: Colab / Kaggle · Registry: Hugging Face · Watchdog: Cloudflare</span>
      </footer>
    </main>
  );
}
