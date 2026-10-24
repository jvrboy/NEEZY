function value(number, digits = 2) {
  return typeof number === "number" && Number.isFinite(number) ? number.toFixed(digits) : "—";
}

export default function Diagnostics({ status, paused, heartbeat, unavailable }) {
  const insights = status?.insights;
  if (!insights) return <section className="panel"><h2>Executor diagnostics</h2><p className="muted">Diagnostics require a successful snapshot from the updated Python executor. No sample metrics are substituted.</p></section>;
  const { equity, quality, positions } = insights;
  const fresh = typeof heartbeat === "number" && heartbeat <= 120 && !unavailable;
  return <>
    <section className="panel">
      <div className="panel-heading"><div><span className="eyebrow">OBSERVABILITY</span><h2>Snapshot quality</h2></div><span className={fresh && !paused ? "model-active" : "model-inactive"}>{paused ? "PAUSED" : fresh ? "FRESH" : "STALE"}</span></div>
      <dl className="health-list">
        <div><dt>Heartbeat age</dt><dd>{value(heartbeat, 1)} seconds</dd></div>
        <div><dt>Current issues</dt><dd>{quality.issue_count}</dd></div>
        <div><dt>Active / registered models</dt><dd>{quality.active_models} / {quality.registered_models}</dd></div>
        <div><dt>Accepted / rejected equity samples</dt><dd>{equity.samples} / {equity.rejected_samples}</dd></div>
      </dl>
    </section>
    <div className="metrics-grid">
      <section className="metric"><span className="metric-label">Window equity change</span><strong>{value(equity.window_change)}</strong><span className="metric-detail">{value(equity.window_change_percent)}% · may include cash flows</span></section>
      <section className="metric"><span className="metric-label">Window max drawdown</span><strong>{value(equity.max_drawdown_percent)}%</strong><span className="metric-detail">Not account lifetime drawdown</span></section>
      <section className="metric"><span className="metric-label">Current drawdown</span><strong>{value(equity.current_drawdown_percent)}%</strong><span className="metric-detail">From observed window peak</span></section>
      <section className="metric"><span className="metric-label">Largest symbol share</span><strong>{value(positions.largest_symbol_share_percent)}%</strong><span className="metric-detail">By position count, not notional risk</span></section>
    </div>
    <section className="panel"><span className="eyebrow">POSITION DISTRIBUTION</span><h2>Markets in the current snapshot</h2>
      <div className="distribution">{Object.entries(positions.by_symbol || {}).map(([symbol, count]) => <div key={symbol}><span>{symbol}</span><meter min="0" max={positions.total || 1} value={count} aria-label={`${symbol} position count`} /><strong>{count}</strong></div>)}</div>
      {!positions.total && <p className="empty">No open positions reported.</p>}
      <p className="muted">{positions.measurement}. {equity.scope}. {insights.warning}</p>
    </section>
  </>;
}
