export function filterPositions(positions, { query = "", side = "all", sort = "ticket" } = {}) {
  const source = Array.isArray(positions) ? positions : [];
  const search = String(query).toLowerCase().trim();
  return source.filter((trade) => trade && typeof trade === "object"
    && `${trade.symbol || ""} ${trade.ticket || ""}`.toLowerCase().includes(search)
    && (side === "all" || String(trade.type).toLowerCase() === side))
    .sort((a, b) => sort === "profit" ? (Number(b.profit) || 0) - (Number(a.profit) || 0)
      : sort === "symbol" ? String(a.symbol).localeCompare(String(b.symbol))
        : (Number(b.ticket) || 0) - (Number(a.ticket) || 0));
}
