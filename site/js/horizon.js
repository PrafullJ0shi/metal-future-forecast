// Pure helpers: pull the 1-hour holding-horizon row of the main signal out of backtest.json.
// Returns null when the file or the 1h row is missing. Never invents a number.

export function oneHourRow(backtest, metal) {
  const sum = backtest?.metals?.[metal]?.summary;
  const row = sum?.horizons?.hourly?.max_h?.["1h"];
  const sig = row?.signal;
  if (!sig || !Number.isFinite(sig.trades) || !Number.isFinite(sig.hit_rate) || !Number.isFinite(sig.avg_net)) {
    return null;
  }
  const w = sum.windows?.max_h || {};
  return {
    metal,
    trades: sig.trades,
    hit_rate: sig.hit_rate,
    avg_net: sig.avg_net,
    start_ms: Number.isFinite(w.start_ms) ? w.start_ms : (sum.hourly_from_ms ?? null),
    end_ms: Number.isFinite(w.end_ms) ? w.end_ms : null,
  };
}

export function oneHourCites(backtest, metals = ["gold", "silver"]) {
  if (!backtest || typeof backtest !== "object") return null;
  const out = {};
  let any = false;
  for (const k of metals) {
    const row = oneHourRow(backtest, k);
    if (row) { out[k] = row; any = true; }
  }
  return any ? out : null;
}

// Hit rate is the share of trades whose direction was right before costs (same wording as Table 5).
// Average net is after fees and funding, in decimal return per trade.
export function citeLine(row, name, dayFmt) {
  if (!row) return null;
  const hit = (row.hit_rate * 100).toFixed(1) + "%";
  const netBp = (row.avg_net * 1e4);
  const net = (netBp < 0 ? "−" : netBp > 0 ? "+" : "") + Math.abs(netBp).toFixed(1) + " bp";
  const after = row.avg_net < 0 ? "loses money after costs" : "makes money after costs";
  const when = (row.start_ms && row.end_ms && dayFmt)
    ? ` ${dayFmt(row.start_ms)} to ${dayFmt(row.end_ms)}.`
    : ".";
  return `${name}: ${row.trades.toLocaleString("en-US")} one-hour trades, hit rate ${hit} before costs, average net ${net} (${after}). Window:${when}`;
}
