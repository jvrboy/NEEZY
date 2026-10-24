"use client";

import { useState } from "react";
import { parseResearchReport } from "../../lib/research-report.mjs";

function number(value, digits = 3) { return typeof value === "number" && Number.isFinite(value) ? value.toFixed(digits) : "—"; }

export default function ResearchReport() {
  const [report, setReport] = useState(null);
  const [error, setError] = useState("");
  async function load(event) {
    const file = event.target.files?.[0];
    if (!file) return;
    setError(""); setReport(null);
    try {
      if (file.size > 5_000_000) throw new Error("Report exceeds 5 MB.");
      setReport(parseResearchReport(await file.text()));
    } catch (reason) { setError(reason instanceof SyntaxError ? "The file is not valid JSON." : reason.message); }
    event.target.value = "";
  }
  const holdout = report?.kind === "chronological-holdout";
  return <section className="panel" aria-labelledby="report-heading">
    <div className="panel-heading"><div><span className="eyebrow">LOCAL EXPERIMENTS</span><h2 id="report-heading">Research report viewer</h2></div><span className="mode-badge">STAYS IN YOUR BROWSER</span></div>
    <p className="muted">Open JSON output from <code>neezy-cli lab analyze</code> or <code>neezy-cli lab evaluate</code>. Files are parsed locally, not uploaded or executed.</p>
    <label className="field">Open advisory lab report<input type="file" accept=".json,application/json" onChange={load} /></label>
    {error && <p className="error-banner" role="alert">{error}</p>}
    {report && <>
      <div className="report-heading"><h3>{report.symbol} · {report.engine} / {report.indicator}</h3><button type="button" onClick={() => setReport(null)}>Clear report</button></div>
      <p className="muted">{report.bars} closed bars · {holdout ? "Chronological holdout" : report.latest.ready ? "Latest output past warm-up" : "Warming up — do not interpret as a ready signal"}</p>
      {holdout ? <>
        <dl className="health-list">
          <div><dt>Non-overlapping observations</dt><dd>{report.observations}</dd></div>
          <div><dt>Net positive share</dt><dd>{report.hit_rate === null ? "—" : `${number(report.hit_rate * 100, 1)}%`}</dd></div>
          <div><dt>Mean hypothetical net change</dt><dd>{number(report.mean_net_bps)} bps</dd></div>
          <div><dt>Fixed round-trip cost</dt><dd>{number(report.cost_bps)} bps</dd></div>
          <div><dt>Holding horizon</dt><dd>{report.horizon} bars</dd></div>
        </dl><p className="warning">Simplified next-open / horizon-close evaluation. No position sizing, leverage, spread model or market impact. Not evidence of profitability.</p>
      </> : <div className="table-scroll"><table><thead><tr><th>Output</th><th>Latest value</th></tr></thead><tbody>{Object.entries(report.latest.values).map(([name, value]) => <tr key={name}><td>{name}</td><td>{typeof value === "number" ? number(value, 6) : value === null ? "Warm-up / unavailable" : String(value)}</td></tr>)}</tbody></table></div>}
      <p className="warning">Advisory research only. This file does not change executor settings or authorize orders.</p>
    </>}
    {!report && <p className="empty">No research report loaded.</p>}
  </section>;
}
