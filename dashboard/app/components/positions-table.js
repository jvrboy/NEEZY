"use client";

import { useState } from "react";
import { filterPositions } from "../../lib/positions.mjs";

function number(value, digits = 2) {
  return value !== null && value !== undefined && value !== "" && Number.isFinite(Number(value))
    ? Number(value).toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits }) : "—";
}
export default function PositionsTable({ trades }) {
  const [query, setQuery] = useState("");
  const [side, setSide] = useState("all");
  const [sort, setSort] = useState("ticket");
  const visible = filterPositions(trades, { query, side, sort });
  return <section className="panel">
    <div className="panel-heading"><div><span className="eyebrow">BROKER POSITIONS</span><h2>Open trades</h2></div><span className="subtle">Read-only · broker-side SL/TP</span></div>
    <div className="table-tools">
      <label className="field">Market or ticket<input type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search positions" /></label>
      <label className="field">Direction<select value={side} onChange={(event) => setSide(event.target.value)}><option value="all">All sides</option><option value="buy">Buy</option><option value="sell">Sell</option></select></label>
      <label className="field">Sort positions<select value={sort} onChange={(event) => setSort(event.target.value)}><option value="ticket">Newest ticket</option><option value="symbol">Market name</option><option value="profit">P / L descending</option></select></label>
      <span className="subtle" role="status">{visible.length} / {trades.length} shown</span>
    </div>
    <div className="table-scroll"><table><caption className="sr-only">Open broker positions filtered by market and side</caption><thead><tr><th>Ticket</th><th>Market</th><th>Side</th><th>Size</th><th>Entry</th><th>Stop loss</th><th>Take profit</th><th className="align-right">P / L</th></tr></thead>
      <tbody>{visible.map((trade) => <tr key={trade.ticket}><td className="muted">#{trade.ticket}</td><td><strong>{trade.symbol}</strong></td><td><span className={`side ${String(trade.type).toLowerCase()}`}>{trade.type}</span></td><td>{number(trade.volume)}</td><td>{number(trade.price_open, 5)}</td><td>{number(trade.sl, 5)}</td><td>{number(trade.tp, 5)}</td><td className={`align-right ${Number(trade.profit) >= 0 ? "positive" : "negative"}`}>{number(trade.profit)}</td></tr>)}
      {!visible.length && <tr><td colSpan="8" className="empty">{trades.length ? "No positions match the current filters." : "No open positions reported."}</td></tr>}</tbody></table></div>
  </section>;
}
