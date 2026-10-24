"use client";

import { useEffect, useState } from "react";

export default function ResearchLibrary() {
  const [document, setDocument] = useState(null);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/capabilities", { signal: controller.signal, cache: "no-store" })
      .then(async (response) => {
        if (!response.ok) throw new Error("Capability discovery unavailable");
        const data = await response.json();
        if (!Array.isArray(data.engines)) throw new Error("Invalid capabilities");
        setDocument(data);
      }).catch((reason) => { if (reason.name !== "AbortError") setError("Connect an updated executor to discover installed research engines."); });
    return () => controller.abort();
  }, []);
  const engines = (document?.engines || []).filter((engine) => `${engine.name} ${engine.indicators.join(" ")}`.toLowerCase().includes(query.toLowerCase()));
  return <section className="panel" aria-labelledby="library-heading">
    <div className="panel-heading"><div><span className="eyebrow">ARCHIVE RESEARCH</span><h2 id="library-heading">Indicator library</h2></div><span className="mode-badge">ADVISORY ONLY</span></div>
    <p className="muted">Isolated reference engines. Closed candles only. No broker orders, no automatic model promotion.</p>
    <label className="field">Search engines or indicators<input type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="FRAS, EDI, volatility…" /></label>
    {error && <p role="status" className="warning">{error}</p>}
    {!document && !error && <p role="status">Discovering research capabilities…</p>}
    <div className="library-grid">{engines.map((engine) => <article className="model-card" key={engine.id}>
      <div className="model-title"><strong>{engine.name}</strong><span className={engine.available ? "model-active" : "model-inactive"}>{engine.available ? "AVAILABLE" : "OPTIONAL"}</span></div>
      <div className="indicator-chips">{engine.indicators.map((indicator) => <span key={indicator}>{indicator}</span>)}</div>
      <p>{engine.requires_numpy ? "Python / NumPy reference engine" : "Zero additional runtime dependencies"}</p>
      {engine.install_hint && <code>{engine.install_hint}</code>}
    </article>)}</div>
    {document && !engines.length && <p className="empty">No engines match your search.</p>}
    <div className="research-help"><h3>Run a local experiment</h3><code>neezy-cli lab catalog --json</code><code>neezy-cli lab analyze --input candles.json --engine fras --series</code><p className="muted">Input rows: [epoch, open, high, low, close, optional_ticks]. Maximum {document?.max_bars || 5000} bars. This dashboard lists capabilities; experiments run locally in the CLI.</p></div>
  </section>;
}
