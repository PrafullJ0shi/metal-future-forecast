import { usd, px, pct, num, p2, cls, when, ago, esc, short, day, tzLabel } from "./fmt.js";
import { lineChart, gauge } from "./charts.js";
import { initFlows } from "./flows.js";
import { initBacktest } from "./backtest.js";

const METALS = ["gold", "silver"];
const COLOR = { gold: "#F5B700", silver: "#C0C6CC" };
const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
if (reduce) document.querySelectorAll("animate.anim").forEach(a => a.remove());

// <use> content lives in a closed shadow tree, so CSS cannot reach the mascots' eyes and mouths.
// Inline the symbol so the verdict classes (and the blink) apply.
export function inlineMascots(root = document) {
  root.querySelectorAll('svg > use[href="#nugget"], svg > use[href="#quick"]').forEach(u => {
    const sym = document.querySelector(u.getAttribute("href"));
    if (sym) u.parentNode.innerHTML = sym.innerHTML;
  });
}
inlineMascots();

const SLANG = {
  LONG: m => [`${m} is cooking`, "The weighted money leans long. Send it? Check the interval before you ape."],
  SHORT: m => [`${m} getting rekt`, "The weighted money leans short. Bag holders, maybe touch grass."],
  NEUTRAL: m => [`${m} is just vibing`, "Neither side holds 60% of the weight. Sit on hands, ser."],
};

const state = { data: null, hist: {} };

async function getJSON(url) {
  const r = await fetch(url, { cache: "no-store" });
  if (!r.ok) throw new Error(url + " " + r.status);
  return r.json();
}

function setMascot(metal, verdict) {
  const el = document.getElementById("mascot-" + metal);
  if (!el) return;
  el.classList.remove("v-LONG", "v-SHORT", "v-NEUTRAL");
  el.classList.add("v-" + verdict);
  el.setAttribute("aria-label", `${metal === "gold" ? "Nugget, the gold mascot" : "Quicksilver, the silver mascot"}: ${verdict}`);
}

function card(m) {
  const name = m.label, v = m.verdict, mk = m.market || {};
  const [slang, sub] = SLANG[v](name);
  const weak = m.ci_low != null && m.ci_low <= 0.5 && m.ci_high >= 0.5;
  const voters = m.n_long + m.n_short;
  const notes = [];
  if (weak) notes.push("The 95% interval crosses 0.50, so this call is weakly held.");
  if (voters < 20) notes.push(`Only ${voters} wallets in the top 500 hold ${name.toLowerCase()} right now; a few bags can swing it.`);
  return `
  <div class="mc-head">
    <svg viewBox="0 0 160 160" aria-hidden="true"><use href="#${m.metal === "gold" ? "nugget" : "quick"}"/></svg>
    <div><h2 class="mc-name">${esc(name)}</h2><p class="mc-coin"><code>${esc(m.coin)}</code> &middot; ${esc(m.underlying)}</p></div>
    <div class="mc-px"><span class="px">${px(m.mark)}</span><span class="chg ${cls(mk.change_24h)}">${pct(mk.change_24h, 2)} 24h</span></div>
  </div>
  <div class="verdict-row">
    <div class="verdict ${v}" aria-label="Verdict ${v}">${v}</div>
    <div><p class="slang">${esc(slang)}</p><p class="slang-sub">${esc(sub)}</p></div>
  </div>
  <p class="big-p"><b>${p2(m.p_long)}</b> weighted P(long) &middot; 95% interval ${p2(m.ci_low)} to ${p2(m.ci_high)}</p>
  <div class="gauge" data-gauge="${m.metal}"></div>
  <ul class="stats">
    <li><span class="k">Long wallets</span><span class="v up">${m.n_long}</span></li>
    <li><span class="k">Short wallets</span><span class="v down">${m.n_short}</span></li>
    <li><span class="k">Long notional</span><span class="v">${usd(m.notional_long)}</span></li>
    <li><span class="k">Short notional</span><span class="v">${usd(m.notional_short)}</span></li>
    <li><span class="k">No position (no vote)</span><span class="v">${m.n_flat}</span></li>
    <li><span class="k">Beta interval (headcount)</span><span class="v">${p2(m.beta_ci_low)}–${p2(m.beta_ci_high)}</span></li>
    <li><span class="k">Funding, hourly</span><span class="v ${cls(-mk.funding_hourly)}">${pct(mk.funding_hourly, 4)}</span></li>
    <li><span class="k">Open interest</span><span class="v">${usd(mk.open_interest_usd)}</span></li>
  </ul>
  ${notes.length ? `<ul class="card-notes">${notes.map(n => `<li>${esc(n)}</li>`).join("")}</ul>` : ""}`;
}

function drawGauges() {
  for (const k of METALS) {
    const m = state.data?.metals?.[k]; const el = document.querySelector(`[data-gauge="${k}"]`);
    if (m && el) el.innerHTML = gauge(el.clientWidth, m.p_long, m.ci_low, m.ci_high, COLOR[k]);
  }
}

function histFmt() {
  const ts = METALS.flatMap(k => (state.hist[k] || []).map(h => Date.parse(h.ts_utc)));
  const span = ts.length ? Math.max(...ts) - Math.min(...ts) : 0;
  return span < 2 * 86400e3 ? v => when(v, false).replace(/ \S+$/, "") : v => day(v);
}

function drawCharts() {
  const hx = document.getElementById("hist-chart");
  if (hx && hx.offsetParent) {
    lineChart(hx, {
      series: METALS.map(k => ({ color: COLOR[k], dots: true, width: 2,
        points: (state.hist[k] || []).filter(h => h.p_long != null).map(h => [Date.parse(h.ts_utc), h.p_long]) })),
      yDomain: [0, 1], yTicks: [0, .2, .4, .6, .8, 1], thresholds: [.4, .6], yFmt: v => v.toFixed(1),
      xFmt: histFmt(), xTicks: 4, empty: "One sweep so far. The line grows every 30 minutes.",
    });
  }
  const pc = document.getElementById("price-chart");
  if (pc && pc.offsetParent) {
    lineChart(pc, {
      series: METALS.map(k => {
        const c = state.data.metals[k]?.market?.chart_1h || []; const b = c.length ? c[0][4] : 1;
        return { color: COLOR[k], width: 2, points: c.map(r => [r[0], r[4] / b * 100]) };
      }),
      yFmt: v => v.toFixed(1), xFmt: v => day(v),
    });
  }
}

function marketTable(d) {
  const rows = [
    ["Mark price", m => px(m.market.mark)],
    ["24h / 7d / 30d move", m => `<span class="${cls(m.market.change_24h)}">${pct(m.market.change_24h, 2)}</span> / <span class="${cls(m.market.change_7d)}">${pct(m.market.change_7d, 2)}</span> / <span class="${cls(m.market.change_30d)}">${pct(m.market.change_30d, 2)}</span>`],
    ["Funding now (hourly, annualised)", m => `${pct(m.market.funding_hourly, 4)} (${pct(m.market.funding_annualised, 1)} a year)`],
    ["Funding, 24h and 7d average", m => `${pct(m.market.funding_24h_avg, 4)} / ${pct(m.market.funding_7d_avg, 4)}`],
    ["Open interest", m => `${num(m.market.open_interest, 0)} oz (${usd(m.market.open_interest_usd)})`],
    ["24h volume", m => usd(m.market.day_volume_usd)],
    ["Trend (hourly EMA 20 / 50 / 200)", m => esc(m.market.ema?.state || "–")],
    ["Regime", m => `${esc(m.market.regime?.label || "–")}${m.market.regime?.sub ? " (" + esc(m.market.regime.sub) + ")" : ""}`],
    ["24h realised vol (annualised)", m => pct(m.market.realised_vol_24h, 1, false)],
    ["Taker fee on this market", m => pct(m.taker_fee, 3, false) + (m.metal === "gold" ? " (standard HIP-3)" : " (growth mode)")],
  ];
  const head = `<tr><th>Reading</th>${METALS.map(k => `<th class="num">${esc(d.metals[k].label)}</th>`).join("")}</tr>`;
  const body = rows.map(([l, f]) => `<tr><td class="lbl">${l}</td>${METALS.map(k => `<td class="num">${f(d.metals[k])}</td>`).join("")}</tr>`).join("");
  document.getElementById("market-table").innerHTML = head + body;
  const r = d.reference?.PAXG;
  if (r && r.mark) document.getElementById("paxg-note").innerHTML =
    `Reference only: <code>PAXG</code> on the validator dex is a perp on a gold-backed token, not on spot gold. It trades at ${px(r.mark)}, ${pct(r.basis_vs_gold, 2)} against xyz:GOLD, with ${usd(r.open_interest * r.mark)} open interest. The signal uses xyz:GOLD only, because that is where the leaders' gold money sits.`;
}

function posTable(m, id) {
  const rows = (m.top_positions || []).slice(0, 10);
  const el = document.getElementById(id);
  if (!rows.length) { el.outerHTML = emptyState(`Nobody in the top 500 holds ${m.label.toLowerCase()} right now. Ghost town.`); return; }
  el.innerHTML = `<tr><th>Wallet</th><th>Side</th><th class="num">Notional</th><th class="num">Lev.</th><th class="num">uPnL</th><th class="num">Weight</th></tr>` +
    rows.map(r => `<tr><td><a class="addr" href="https://app.hyperliquid.xyz/explorer/address/${r.address}" rel="noopener">${esc(r.display_name || short(r.address))}</a></td>
    <td><span class="tag ${r.side}">${r.side}</span></td><td class="num">${usd(r.notional)}</td><td class="num">${r.leverage ? num(r.leverage, 0) + "×" : "–"}</td>
    <td class="num ${cls(r.unrealized_pnl)}">${usd(r.unrealized_pnl)}</td><td class="num">${num(r.weight, 2)}</td></tr>`).join("");
}

export function emptyState(text) {
  const body = document.getElementById("quick")?.innerHTML || "";
  return `<div class="empty-state"><svg class="mascot-mini v-NEUTRAL" viewBox="0 0 160 160" aria-hidden="true">${body}</svg><span>${esc(text)}</span></div>`;
}

function changes(d) {
  let h = "";
  for (const k of METALS) {
    const c = d.metals[k].changes || {};
    h += `<h3 class="ptitle" style="font-size:19px;margin-top:6px">${esc(d.metals[k].label)}</h3>`;
    if (!c.available) { h += emptyState(c.reason || "Building history."); continue; }
    if (!c.items.length) { h += emptyState("Nobody touched their bags. Diamond hands or asleep."); continue; }
    const ct = c.counts;
    h += `<p class="psub">Since ${when(Date.parse(c.since_utc))}: ${ct.opened} opened, ${ct.closed} closed, ${ct.flipped} flipped, ${ct.added} added, ${ct.trimmed} trimmed.</p>`;
    h += `<div class="table-wrap"><table class="data compact"><tr><th>Wallet</th><th>What</th><th class="num">Change</th><th>Now</th></tr>` +
      c.items.slice(0, 6).map(i => `<tr><td class="addr">${short(i.address)}</td><td>${i.kind}</td><td class="num ${cls(i.delta_usd)}">${usd(i.delta_usd)}</td><td><span class="tag ${i.side_now}">${i.side_now}</span></td></tr>`).join("") + `</table></div>`;
  }
  document.getElementById("changes").innerHTML = h;
}

function risk(d) {
  document.getElementById("risk").innerHTML = `<div class="table-wrap"><table class="data"><tr><th>Reading</th>${METALS.map(k => `<th class="num">${esc(d.metals[k].label)}</th>`).join("")}</tr>` +
    [["Median leverage", r => r.median_leverage ? num(r.median_leverage, 0) + "×" : "–"],
     ["Highest leverage (degen mode)", r => r.max_leverage ? num(r.max_leverage, 0) + "×" : "–"],
     ["Median distance to liquidation", r => pct(r.median_liq_distance, 1, false)],
     ["Positions within 5% of liquidation", r => `${r.within_5pct ?? "–"} of ${r.with_liq_price ?? "–"}`]]
      .map(([l, f]) => `<tr><td class="lbl">${l}</td>${METALS.map(k => `<td class="num">${f(d.metals[k].risk || {})}</td>`).join("")}</tr>`).join("") +
    `</table></div><p class="note">Cross-margin positions often show no liquidation price, so they are left out of the distance rows.</p>`;
}

function stamp(d) {
  const c = d.cohort || {};
  document.getElementById("stamp").innerHTML = `Poured <b>${when(d.generated_ms)}</b> (${ago(d.generated_ms)}) &middot; ${c.n_top} top wallets, ${c.n_contrast} ngmi wallets &middot; refreshed about every 30 minutes`;
}

// Tabs with hash routing.
const TABS = ["signal", "flows", "backtest"];
const inited = {};
function show(id) {
  if (!TABS.includes(id)) id = "signal";
  for (const t of TABS) {
    document.getElementById("panel-" + t).hidden = t !== id;
    const a = document.getElementById("tab-" + t);
    a.setAttribute("aria-selected", String(t === id)); a.tabIndex = t === id ? 0 : -1;
  }
  if (id === "flows" && state.data && !inited.flows) { inited.flows = true; initFlows(state.data); }
  if (id === "backtest" && !inited.backtest) { inited.backtest = true; initBacktest(); }
  if (id === "signal") requestAnimationFrame(() => { drawGauges(); drawCharts(); });
  window.dispatchEvent(new Event("tabshown"));
}
window.addEventListener("hashchange", () => show(location.hash.slice(1)));
document.querySelector(".tabs").addEventListener("keydown", e => {
  if (!["ArrowLeft", "ArrowRight"].includes(e.key)) return;
  const i = TABS.indexOf(location.hash.slice(1) || "signal"), j = (i + (e.key === "ArrowRight" ? 1 : TABS.length - 1)) % TABS.length;
  location.hash = TABS[j]; document.getElementById("tab-" + TABS[j]).focus();
});

let rt;
window.addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(() => { drawGauges(); drawCharts(); window.dispatchEvent(new Event("redraw")); }, 150); });

async function main() {
  try {
    const d = await getJSON("data/signal.json");
    state.data = d;
    const hs = await Promise.all(METALS.map(k => getJSON(`data/history_${k}.json`).catch(() => [])));
    METALS.forEach((k, i) => state.hist[k] = hs[i]);
    for (const k of METALS) {
      const m = d.metals[k];
      document.getElementById("card-" + k).innerHTML = card(m);
      inlineMascots(document.getElementById("card-" + k));
      document.querySelector(`#card-${k} .mc-head svg`).classList.add("mascot-mini", "v-" + m.verdict);
      setMascot(k, m.verdict);
      posTable(m, "pos-" + k);
    }
    stamp(d); marketTable(d); changes(d); risk(d);
  } catch (e) {
    document.getElementById("stamp").textContent = "Could not load the latest snapshot. The furnace is cold; try again in a minute.";
    console.error(e);
  }
  show(location.hash.slice(1) || "signal");
}
main();
