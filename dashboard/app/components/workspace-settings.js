"use client";

export default function WorkspaceSettings({ preferences, onChange }) {
  function update(key, value) { onChange({ ...preferences, [key]: value }); }
  return <section className="panel" aria-labelledby="settings-heading">
    <div className="panel-heading"><div><span className="eyebrow">YOUR WORKSPACE</span><h2 id="settings-heading">Appearance & monitoring</h2></div><span className="mode-badge">BROWSER LOCAL</span></div>
    <p className="muted">Preferences affect only this browser. They cannot change broker configuration, risk limits, model promotion, or execution permissions.</p>
    <div className="settings-grid">
      <label className="field">Color theme<select value={preferences.theme} onChange={(event) => update("theme", event.target.value)}><option value="emerald">Liquid emerald</option><option value="midnight">Midnight blue</option><option value="contrast">High contrast</option></select></label>
      <label className="field">Information density<select value={preferences.density} onChange={(event) => update("density", event.target.value)}><option value="comfortable">Comfortable</option><option value="compact">Compact</option></select></label>
      <label className="field">Refresh interval<select value={preferences.refreshSeconds} onChange={(event) => update("refreshSeconds", Number(event.target.value))}>{[15, 30, 60, 120].map((value) => <option key={value} value={value}>{value} seconds</option>)}</select></label>
      <label className="field">Heartbeat stale threshold<select value={preferences.staleSeconds} onChange={(event) => update("staleSeconds", Number(event.target.value))}>{[60, 120, 300].map((value) => <option key={value} value={value}>{value} seconds</option>)}</select></label>
      <label className="check-field"><input type="checkbox" checked={preferences.reducedMotion} onChange={(event) => update("reducedMotion", event.target.checked)} />Reduce decorative motion</label>
    </div>
    <h3>Safety boundaries</h3><p className="muted">The executor API remains loopback-only and read-only. Provider credentials stay on the server. Research engines are separate from order execution.</p>
  </section>;
}
