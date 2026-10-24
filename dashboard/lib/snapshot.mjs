const object = (value) => value && typeof value === "object" && !Array.isArray(value) ? value : {};
export function normalizeSnapshot(input) {
  const data = object(input);
  if (Object.keys(data).length === 0) throw new Error("empty executor snapshot");
  return {
    ...data,
    account: object(data.account), broker: object(data.broker), risk: object(data.risk), execution: object(data.execution),
    models: Object.fromEntries(Object.entries(object(data.models)).filter(([, model]) => model && typeof model === "object" && !Array.isArray(model))),
    open_trades: (Array.isArray(data.open_trades) ? data.open_trades : []).filter((trade) => trade && typeof trade === "object" && !Array.isArray(trade)),
    issues: (Array.isArray(data.issues) ? data.issues : []).filter((issue) => issue && typeof issue === "object"),
    equity_history: (Array.isArray(data.equity_history) ? data.equity_history : []).filter((sample) => sample && typeof sample === "object" && sample.equity !== null && typeof sample.equity === "number" && Number.isFinite(sample.equity)),
  };
}
export function heartbeatAge(snapshot, receivedAt, now) {
  const age = snapshot?.heartbeat_age_seconds;
  if (typeof age !== "number" || !Number.isFinite(age)) return null;
  return Math.max(0, age) + (receivedAt && now ? Math.max(0, now - receivedAt) / 1000 : 0);
}
