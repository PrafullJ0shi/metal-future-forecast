import { pct, num, when, day, esc, cls } from "./fmt.js";
import { lineChart } from "./charts.js";

let B, metal = "gold", win = "listing", hzWin = "hourly:max_h";
const NAMES = { signal: "Follow the signal", long_only: "Long-only", short_only: "Short-only", fade: "Fade the signal", hold: "Buy and hold", short: "Always short" };
const COL = { signal: null, long_only: "#7BD88F", short_only: "#C77DFF", fade: "#8A9299", hold: "#6FA8DC", short: "#FF6B6B" };
const WINS = [
  ["listing", "Since listing", "Since listing, daily bars: the longest test the data allows"],
  ["oos_d", "Before the ranking month", "Since listing up to the month the cohort was ranked on (daily bars): the cleanest out-of-sample read"],
  ["max_h", "Hourly max", "Every hour with an hourly candle (the API keeps the latest 5,000)"],
  ["oos_h", "Hourly, before ranking month", "Hourly bars up to the month the cohort was ranked on"],
  ["90d", "90d", "Last 90 days, hourly bars"],
  ["30d", "30d", "Last 30 days, hourly bars"],
];
const INS = { yes: "in-sample", partial: "includes in-sample month", no: "out-of-sample" };
const colorFor = k => k === "signal" ? (metal === "gold" ? "#F5B700" : "#EEF1F4") : COL[k];
const unit = w => w.grid === "hourly" ? "hour" : "day";
const M_ = () => B.metals[metal];
const W_ = () => M_().summary.windows[win];

function hero() {
  const el = document.getElementById("bt-hero");
  const parts = ["gold", "silver"].map(k => {
    const s = B.metals[k].summary, w = s.windows.listing, o = s.windows.oos_d, st = w.strategies;
    const best = Math.max(st.hold.total_return, st.short.total_return);
    const edge = st.signal.total_return - best;
    return `<div class="bt-card ${k}"><h3>${k === "gold" ? "Gold" : "Silver"} &middot; ${day(w.start_ms)} to ${day(w.end_ms)}</h3><dl>
      <dt>Follow the signal</dt><dd class="${cls(st.signal.total_return)}">${pct(st.signal.total_return)}</dd>
      <dt>Buy and hold</dt><dd class="${cls(st.hold.total_return)}">${pct(st.hold.total_return)}</dd>
      <dt>Always short</dt><dd class="${cls(st.short.total_return)}">${pct(st.short.total_return)}</dd>
      <dt>Signal minus the better baseline</dt><dd class="${cls(edge)}">${pct(edge)}</dd>
      <dt>Out-of-sample part (to ${day(o.end_ms)})</dt><dd class="${cls(o.strategies.signal.total_return)}">${pct(o.strategies.signal.total_return)} vs hold ${pct(o.strategies.hold.total_return)}</dd>
      <dt>Sharpe-like (signal / hold)</dt><dd>${num(st.signal.sharpe_like, 2)} / ${num(st.hold.sharpe_like, 2)}</dd>
      <dt>Max drawdown (signal)</dt><dd class="down">${pct(st.signal.max_drawdown)}</dd>
      <dt>Days in the market</dt><dd>${pct(st.signal.time_in_market, 0, false)} of ${num(w.bars, 0)}</dd></dl></div>`;
  });
  el.innerHTML = `<h2>Would aping the leaders have paid?</h2><p class="lede">${esc(B.headline || "")}</p><div class="bt-cards">${parts.join("")}</div>
  <p class="note">The signal for each UTC day uses every cohort wallet's average position the day before (that is all Hyperliquid keeps for older history), then holds one unit of notional through the day. Taker fee on every position change (xyz:GOLD 0.09%, xyz:SILVER 0.009%) and hourly funding included. Thresholds 0.60 / 0.40 were fixed by the BTC project before any metal data was looked at. Not financial advice.</p>`;
}

function windowChips() {
  const s = M_().summary;
  document.getElementById("bt-window").innerHTML = WINS.filter(w => s.windows[w[0]]).map(([k, lab]) =>
    `<button type="button" data-w="${k}" aria-pressed="${k === win}" title="${esc(INS[s.windows[k].in_sample])}">${lab}${s.windows[k].in_sample === "yes" ? " (in-sample)" : s.windows[k].in_sample === "no" ? " (OOS)" : ""}</button>`).join("");
  document.querySelectorAll("#bt-metal button").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.metal === metal)));
}

function slice(ser, w) {
  const idx = [];
  ser.t.forEach((t, j) => { if (t >= w.start_ms && t < w.end_ms) idx.push(j); });
  return idx;
}

function curves() {
  const w = W_(), ser = M_().series[w.grid];
  const idx = slice(ser, w);
  const keys = ["signal", "long_only", "short_only", "hold", "short", "fade"];
  const series = keys.map(k => {
    const c = ser.curves[k] || []; const base = idx[0] > 0 ? 1 + c[idx[0] - 1] : 1;
    return { color: colorFor(k), width: k === "signal" ? 3 : 1.6, dash: k === "fade" ? "4 4" : null,
      points: idx.map(j => [ser.t[j], ((1 + c[j]) / base - 1) * 100]) };
  });
  const eq = document.getElementById("bt-equity");
  lineChart(eq, { series, yFmt: v => v.toFixed(0) + "%", xFmt: v => day(v), height: eq.clientWidth < 500 ? 260 : 340, thresholds: [0] });
  document.getElementById("bt-eq-legend").innerHTML = keys.map(k => `<span><span class="key" style="background:${colorFor(k)}"></span>${NAMES[k]}</span>`).join("");
  const label = WINS.find(x => x[0] === win)[2];
  document.getElementById("bt-eq-sub").textContent = `${label}. ${when(w.start_ms)} to ${when(w.end_ms)}, ${num(w.bars, 0)} ${w.grid} steps. ${metal === "gold" ? "Gold" : "Silver"} itself moved ${pct(w.metal_return)}. ${w.in_sample === "yes" ? "This window is the month the cohort was ranked on, so it is in-sample: the wallets were picked because they made money here." : w.in_sample === "partial" ? "The last 30 days of this window are the ranking month (in-sample)." : "Ends before the ranking month, so the cohort was not picked on these days."}`;
  const ds = M_().series.daily, didx = slice(ds, w.grid === "daily" ? w : { start_ms: w.start_ms - 86400000, end_ms: w.end_ms });
  const tint = metal === "gold" ? "#F5B700" : "#C0C6CC";
  lineChart(document.getElementById("bt-p"), { series: [{ color: tint, width: 1.8, points: didx.map(j => [ds.t[j], ds.p[j]]) }], yDomain: [0, 1], yTicks: [0, .2, .4, .6, .8, 1], thresholds: [.4, .6], yFmt: v => v.toFixed(1), xFmt: v => day(v), empty: "No reading in this window." });
  const vmax = Math.max(4, ...didx.map(j => Math.max(ds.voters_long[j], ds.voters_short[j])));
  lineChart(document.getElementById("bt-cov"), {
    series: [{ color: "#7BD88F", width: 2, points: didx.map(j => [ds.t[j], ds.voters_long[j]]) },
             { color: "#FF6B6B", width: 2, points: didx.map(j => [ds.t[j], -ds.voters_short[j]]) }],
    yDomain: [-vmax, vmax], thresholds: [0], yFmt: v => Math.abs(v).toFixed(0), xFmt: v => day(v),
  });
}

function table() {
  const w = W_(), u = unit(w);
  const cols = [["Total return", s => pct(s.total_return), true], ["Max drawdown", s => pct(s.max_drawdown)], ["Sharpe-like", s => num(s.sharpe_like, 2)],
    ["Hit rate", s => pct(s.hit_rate, 1, false)], [`Avg / ${u} in market`, s => s.avg_return_per_bar_in_market == null ? "–" : num(s.avg_return_per_bar_in_market * 1e4, 2) + " bp"],
    ["Time in market", s => pct(s.time_in_market, 0, false)], [`Long / short ${u}s`, s => `${s.bars_long} / ${s.bars_short}`], ["Trades", s => s.trades],
    ["Fees", s => pct(s.fees, 2)], ["Funding", s => pct(s.funding, 2)], ["Avg / episode", s => pct(s.avg_return_per_episode, 2)]];
  document.getElementById("bt-table").innerHTML = `<tr><th>Strategy</th>${cols.map(c => `<th class="num">${c[0]}</th>`).join("")}</tr>` +
    Object.keys(NAMES).map(k => { const s = w.strategies[k]; return `<tr class="${k === "signal" ? "hl" : ""}"><td class="lbl"><span class="key" style="background:${colorFor(k)}"></span>${NAMES[k]}</td>${cols.map(c => `<td class="num ${c[2] ? cls(s.total_return) : ""}">${c[1](s)}</td>`).join("")}</tr>`; }).join("");
  document.getElementById("bt-table-note").innerHTML = `Hit rate counts ${u}s in the market where the position matched the next ${u}'s move. An episode is one unbroken run of the same position. Sharpe-like is mean over standard deviation of ${w.grid} net returns, annualised. Cost stress for the signal: doubled fee ${pct(w.stress.fee_x2)}, standard HIP-3 fee (0.09%) ${pct(w.stress.standard_hip3_fee)}.`;
}

function regimes() {
  const w = W_(), u = unit(w);
  document.getElementById("bt-regime-sub").textContent = `Each ${u} is labelled by its trailing 7-day return divided by its own volatility: up above +${B.rules.regime_z}, down below −${B.rules.regime_z}, sideways in between. Labels use only past prices.`;
  const rows = ["up", "down", "sideways"].map(g => { const r = w.regimes[g]; if (!r) return `<tr><td>${g}</td><td colspan="6">no ${u}s</td></tr>`;
    return `<tr><td class="lbl">${g === "up" ? "Up (bulls cooking)" : g === "down" ? "Down (bears feasting)" : "Sideways (crab market)"}</td><td class="num">${r.bars}</td><td class="num ${cls(r.metal_move)}">${pct(r.metal_move)}</td><td class="num ${cls(r.signal.return)}">${pct(r.signal.return)}</td><td class="num">${pct(r.signal.hit_rate, 0, false)}</td><td class="num">${pct(r.share_long, 0, false)} / ${pct(r.share_short, 0, false)}</td><td class="num ${cls(r.hold.return)}">${pct(r.hold.return)}</td></tr>`; });
  document.getElementById("bt-regime").innerHTML = `<tr><th>Regime</th><th class="num">${u[0].toUpperCase() + u.slice(1)}s</th><th class="num">Metal</th><th class="num">Signal</th><th class="num">Hit</th><th class="num">Long / short calls</th><th class="num">Hold</th></tr>` + rows.join("");
}

function grid() {
  const g = M_().summary.grids[W_().grid];
  document.getElementById("bt-grid-sub").innerHTML = `${g.grid === "daily" ? "Daily" : "Hourly"} bars, out-of-sample span split in time order: <span class="tag is">tune</span> ${day(g.tune_start_ms)} to ${day(g.split_ms)}, <span class="tag oos">test</span> ${day(g.split_ms)} to ${day(g.end_ms)}. Only five pairs, picked in advance. The best pair on the tune half was ${g.best_on_tune[0].toFixed(2)} / ${g.best_on_tune[1].toFixed(2)} (starred); read its test column, not the full number.`;
  document.getElementById("bt-grid").innerHTML = `<tr><th>Long / short at</th><th class="num">Tune return</th><th class="num">Test return</th><th class="num">Test Sharpe-like</th><th class="num">Full return</th><th class="num">In market</th></tr>` +
    g.rows.map(r => `<tr class="${r.live ? "hl" : ""}"><td>${r.long.toFixed(2)} / ${r.short.toFixed(2)}${r.live ? " (live)" : ""}${r.long === g.best_on_tune[0] ? " ★" : ""}</td><td class="num ${cls(r.tune.total_return)}">${pct(r.tune.total_return)}</td><td class="num ${cls(r.test.total_return)}">${pct(r.test.total_return)}</td><td class="num">${num(r.test.sharpe_like, 2)}</td><td class="num ${cls(r.full.total_return)}">${pct(r.full.total_return)}</td><td class="num">${pct(r.full.time_in_market, 0, false)}</td></tr>`).join("");
}

function inputs() {
  const I = B.inputs, rows = [];
  for (const [coin, c] of Object.entries(I.market)) {
    rows.push([`${coin} hourly candles`, c.candles_1h.from, c.candles_1h.to, `${c.candles_1h.n} candles; ${c.candles_1h.limit}`]);
    rows.push([`${coin} daily candles`, c.candles_1d.from, c.candles_1d.to, `${c.candles_1d.n} candles, since listing`]);
    rows.push([`${coin} funding`, c.funding.from, c.funding.to, `${c.funding.n} hourly rates`]);
  }
  const w = I.wallets, h = w.history || {};
  rows.push(["Wallet positions (userFunding)", w.history_from, w.history_to, `${h.complete || 0} of ${w.cohort} wallets read in full. Daily figures until ${(w.daily_rows_until || "–").slice(0, 10)}, then the 12:00 UTC funding hour of each day. Ever held gold: ${w.wallets_ever_in.gold}, silver: ${w.wallets_ever_in.silver}. Blind spot: ${w.blind_spot}.`]);
  if (h.assumed_flat) rows.push(["Wallets assumed flat", "–", "–", `${h.assumed_flat} wallets with no xyz account and no metal position today were not read; they count as flat (no vote)`]);
  if (h.missing || h.incomplete) rows.push(["Wallets not read", "–", "–", `${(h.missing || 0) + (h.incomplete || 0)} wallets with an xyz account could not be read in full and are left out (no vote)`]);
  rows.push(["Cohort, month PnL, equity", w.cohort_built_at_utc, w.cohort_built_at_utc, "Today only. Applied to every past day, which flatters the past (survivorship)."]);
  document.getElementById("bt-inputs").innerHTML = `<tr><th>Input</th><th>From (UTC)</th><th>To (UTC)</th><th>Notes</th></tr>` + rows.map(r => `<tr><td class="lbl">${esc(r[0])}</td><td>${esc(r[1] || "–")}</td><td>${esc(r[2] || "–")}</td><td class="lbl">${esc(r[3])}</td></tr>`).join("");
}

function verdict() {
  document.getElementById("bt-verdict").innerHTML = `<h2 class="ptitle">So, edge or no edge?</h2><ol class="steps">${(B.verdict || []).map(v => `<li>${v}</li>`).join("")}</ol>
  <p class="note">Full write-up, CSVs and charts: <a href="https://github.com/PrafullJ0shi/metal-future-forecast/tree/main/research/backtest">research/backtest</a>.</p>`;
}

const HZ_WINS = [["hourly:max_h", "Hourly bars, all (since 1 May)"], ["hourly:oos_h", "Hourly, before ranking month (OOS)"], ["hourly:90d", "Hourly, 90d"], ["hourly:30d", "Hourly, 30d (in-sample)"],
  ["daily:listing", "Daily bars, since listing"], ["daily:oos_d", "Daily, before ranking month (OOS)"]];
const bp = x => x == null ? "–" : (x * 1e4 >= 0 ? "+" : "−") + Math.abs(x * 1e4).toFixed(1) + " bp";

function horizonsView() {
  const [g, wn] = hzWin.split(":"), H = M_().summary.horizons[g][wn];
  document.getElementById("bt-hz-win").innerHTML = HZ_WINS.map(([k, lab]) => `<button type="button" data-hz="${k}" aria-pressed="${k === hzWin}">${lab}</button>`).join("");
  const labs = Object.keys(H);
  const w = M_().summary.windows[wn];
  document.getElementById("bt-hz-sub").innerHTML = `Same call, held for a fixed time. Every N hours (clock-aligned) the latest call is read, the position is held for N hours, then closed. Fee on entry and exit, funding while held. Window: ${when(w.start_ms)} to ${when(w.end_ms)}. ${g === "daily" ? "Daily bars reach back to listing but cannot show anything shorter than a day." : "Hourly candles exist only from 1 May, so this is the short test; it is also the only place 1h to 12h can be measured."}`;
  // Grouped bars: average net per trade, in bp.
  const el = document.getElementById("bt-hz-chart"), W = Math.max(300, el.clientWidth - 12), Ht = W < 500 ? 230 : 280, m = { l: 52, r: 10, t: 14, b: 30 };
  const sides = [["signal", metal === "gold" ? "#F5B700" : "#EEF1F4", "Follow the signal"], ["short", "#FF6B6B", "Always short"], ["long", "#6FA8DC", "Always long"]];
  const vals = labs.flatMap(l => sides.map(([k]) => (H[l][k].avg_net || 0) * 1e4));
  let lo = Math.min(0, ...vals), hi = Math.max(0, ...vals); const pad = (hi - lo) * .08 || 1; lo -= pad; hi += pad;
  const Y = v => m.t + (hi - v) / (hi - lo) * (Ht - m.t - m.b), gw = (W - m.l - m.r) / labs.length, bw = Math.min(26, gw / 4);
  let svg = `<svg viewBox="0 0 ${W} ${Ht}" width="${W}" height="${Ht}" class="lc">`;
  const raw = (hi - lo) / 4, mag = Math.pow(10, Math.floor(Math.log10(raw))), step = [1, 2, 5, 10].map(f => f * mag).find(x => x >= raw);
  for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) { svg += `<line class="grid" x1="${m.l}" x2="${W - m.r}" y1="${Y(v)}" y2="${Y(v)}"/><text class="tick" x="${m.l - 6}" y="${Y(v) + 4}" text-anchor="end">${v.toFixed(0)}</text>`; }
  svg += `<line class="thr" x1="${m.l}" x2="${W - m.r}" y1="${Y(0)}" y2="${Y(0)}"/>`;
  labs.forEach((l, i) => {
    const cx = m.l + gw * (i + .5);
    sides.forEach(([k, c], j) => { const v = (H[l][k].avg_net || 0) * 1e4, x = cx + (j - 1) * (bw + 3) - bw / 2, y0 = Y(0), y1 = Y(v);
      svg += `<rect x="${x}" y="${Math.min(y0, y1)}" width="${bw}" height="${Math.max(1, Math.abs(y1 - y0))}" fill="${c}" rx="3"/>`; });
    svg += `<text class="tick" x="${cx}" y="${Ht - 10}" text-anchor="middle">${l}</text>`;
  });
  el.innerHTML = svg + `<text class="tick" x="${m.l}" y="10">avg net per trade, bp</text></svg>`;
  document.getElementById("bt-hz-legend").innerHTML = sides.map(([, c, n]) => `<span><span class="key" style="background:${c}"></span>${n}</span>`).join("");
  const rows = labs.map(l => { const r = H[l], s = r.signal, sh = r.short; if (!s.trades) return `<tr><td class="lbl">${l}</td><td colspan="9">never in the market</td></tr>`;
    const beats = s.avg_net > Math.max(sh.avg_net ?? -1, r.long.avg_net ?? -1);
    return `<tr><td class="lbl">${l}</td><td class="num">${s.trades}</td><td class="num">${pct(s.hit_rate, 0, false)}</td><td class="num ${cls(s.avg_gross)}">${bp(s.avg_gross)}</td><td class="num ${cls(s.avg_net)}">${bp(s.avg_net)}</td><td class="num ${cls(sh.avg_net)}">${bp(sh.avg_net)}</td><td class="num ${cls(s.total_return)}">${pct(s.total_return)}</td><td class="num down">${pct(s.max_drawdown)}</td><td class="num">${s.n_long} / ${s.n_short}</td><td class="lbl">${s.avg_net < 0 ? "loses money" : beats ? "makes money, beats both baselines" : "makes money, but a baseline did better"}</td></tr>`; }).join("");
  document.getElementById("bt-hz-table").innerHTML = `<tr><th>Horizon</th><th class="num">Trades</th><th class="num">Hit rate</th><th class="num">Avg gross</th><th class="num">Avg net</th><th class="num">Always-short avg net</th><th class="num">Total return</th><th class="num">Max drawdown</th><th class="num">Long / short calls</th><th>Verdict</th></tr>${rows}`;
  const losers = labs.filter(l => H[l].signal.trades && H[l].signal.avg_net < 0);
  document.getElementById("bt-hz-note").innerHTML = `Hit rate is the share of trades whose direction was right before costs. ${losers.length ? `<b>${losers.join(", ")} lose${losers.length === 1 ? "s" : ""} money here after fees and funding.</b> ` : "No horizon loses money in this window. "}Round-trip fees are 0.18% on gold and 0.018% on silver, so the shortest horizons need a very large edge per trade to survive. Few trades at 3d and 1w means those numbers are noisy. Weekly entries are aligned to the Unix week (Thursday 00:00 UTC).`;
}

function render() { windowChips(); curves(); table(); regimes(); grid(); horizonsView(); }

export async function initBacktest() {
  try {
    const [b, extra] = await Promise.all([fetch("backtest/backtest.json", { cache: "no-store" }).then(r => r.json()),
      fetch("backtest/notes.json", { cache: "no-store" }).then(r => r.ok ? r.json() : {}).catch(() => ({}))]);
    B = { ...b, ...extra };
  } catch (e) {
    document.getElementById("bt-hero").innerHTML = "<h2>Backtest still cooking</h2><p class=\"lede\">The wallet position-history pull is running. Numbers land here as soon as it finishes. Touch grass meanwhile.</p>";
    [...document.getElementById("panel-backtest").children].forEach(c => { if (c.id !== "bt-hero") c.hidden = true; });
    return;
  }
  hero(); inputs(); verdict(); render();
  document.getElementById("bt-metal").addEventListener("click", e => { const b = e.target.closest("button"); if (b) { metal = b.dataset.metal; render(); } });
  document.getElementById("bt-hz-win").addEventListener("click", e => { const b = e.target.closest("button"); if (b) { hzWin = b.dataset.hz; horizonsView(); } });
  document.getElementById("bt-window").addEventListener("click", e => { const b = e.target.closest("button"); if (b) { win = b.dataset.w; render(); } });
  window.addEventListener("redraw", () => { if (!document.getElementById("panel-backtest").hidden) { curves(); horizonsView(); } });
}
