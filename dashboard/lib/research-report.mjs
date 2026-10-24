const isObject = (value) => value && typeof value === "object" && !Array.isArray(value);
const finite = (value) => typeof value === "number" && Number.isFinite(value);
const text = (value, max = 80) => typeof value === "string" && value.length > 0 && value.length <= max;
const ENGINES = ["fras", "fxlab", "tideforge", "tideglass"];

export function parseResearchReport(content) {
  if (typeof content !== "string" || content.length > 5_000_000) throw new Error("Report exceeds 5 MB.");
  const data = JSON.parse(content);
  if (!isObject(data) || data.schema !== 1 || data.advisory_only !== true || !ENGINES.includes(data.engine)
      || !text(data.indicator) || !text(data.symbol) || !Number.isInteger(data.bars) || data.bars < 1 || data.bars > 5000) throw new Error("Not a supported advisory NEEZY lab report.");
  if (data.kind === "chronological-holdout") {
    if (!Number.isInteger(data.observations) || data.observations < 0 || data.observations > data.bars
        || !Array.isArray(data.results) || data.results.length !== data.observations
        || !Number.isInteger(data.horizon) || data.horizon < 1 || data.horizon > 100
        || !finite(data.cost_bps) || data.cost_bps < 0
        || !Number.isInteger(data.split_index) || data.split_index < 0 || data.split_index >= data.bars
        || (data.hit_rate !== null && (!finite(data.hit_rate) || data.hit_rate < 0 || data.hit_rate > 1))
        || (data.mean_net_bps !== null && !finite(data.mean_net_bps))) throw new Error("Invalid holdout report.");
    for (const row of data.results) {
      if (!isObject(row) || ![1, -1].includes(row.direction) || !finite(row.net_bps) || !finite(row.gross_bps)
          || !Number.isInteger(row.decision_epoch) || !Number.isInteger(row.entry_epoch) || !Number.isInteger(row.exit_epoch)
          || row.entry_epoch <= row.decision_epoch || row.exit_epoch < row.entry_epoch) throw new Error("Invalid holdout observation.");
    }
    return data;
  }
  function validPoint(point) {
    return isObject(point) && Number.isInteger(point.epoch) && typeof point.ready === "boolean" && isObject(point.values)
      && Object.keys(point.values).length <= 100 && Object.entries(point.values).every(([key, value]) => key.length <= 100
        && (value === null || finite(value) || typeof value === "boolean" || (typeof value === "string" && value.length <= 500)));
  }
  if (!validPoint(data.latest)) throw new Error("Invalid latest indicator output.");
  if (data.series !== undefined && (!Array.isArray(data.series) || data.series.length !== data.bars || !data.series.every(validPoint))) throw new Error("Invalid research series.");
  return data;
}
