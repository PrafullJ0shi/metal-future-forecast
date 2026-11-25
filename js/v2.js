// v2 panels: gold-silver pair check, crowd check per metal, opt-in flip alerts.
import { px, pct, num, p2, cls, esc, when, ago, day, usd, short } from "./fmt.js";
import { lineChart } from "./charts.js";
import { PREF_KEY, parsePrefs, pickToNotify, newestMs, permissionLine, eventTag } from "./alertlogic.js";
import { oneHourCites, citeLine } from "./horizon.js";

const METALS = ["gold", "silver"];
const COLOR = { gold: "#F5B700", silver: "#C0C6CC" };
const LEVEL_COLOR = { STURDY: "var(--up)", SOLID: "var(--gold-500)", WOBBLY: "var(--lava)", JELLY: "var(--down)" };
const NAME = { gold: "Gold", silver: "Silver" };

const empty = (text) => `<p class="note v2-empty">${esc(text)}</p>`;

/* ---------------------------------------------------------------- pair check */

// The plank tips toward the metal the crew favours: gold end up when gold leans more long than silver.
function seesaw(t) {
  const gap = t.gap ?? 0, deg = Math.max(-12, Math.min(12, gap * 14));
  return `<svg class="seesaw" viewBox="0 0 320 150" role="img" aria-label="${esc(t.headline)}. Lean gap ${num(gap, 2)}.">
    <path d="M160 96 L132 138 H188 Z" fill="var(--gold-700)" stroke="var(--ink)" stroke-width="4" stroke-linejoin="round"/>
    <g class="plank" style="--tilt:${deg.toFixed(2)}deg; transform-origin:160px 96px; transform:rotate(${deg.toFixed(2)}deg)">
      <rect x="22" y="88" width="276" height="16" rx="8" fill="url(#chrome)" stroke="var(--ink)" stroke-width="4"/>
      <g transform="translate(58 62)"><circle r="26" fill="url(#gold-body)" stroke="var(--ink)" stroke-width="4"/><circle cx="-9" cy="-10" r="5" fill="#FFF6D6"/>
        <text y="6" text-anchor="middle" class="sw-label" fill="var(--ink)">Au</text></g>
      <g transform="translate(262 68)"><circle r="20" fill="url(#silver-body)" stroke="var(--ink)" stroke-width="4"/><circle cx="-7" cy="-8" r="4" fill="#FFFFFF"/>
        <text y="5" text-anchor="middle" class="sw-label sm" fill="var(--ink)">Ag</text></g>
    </g>
  </svg>`;
}

// Two crisp rows on one -1..+1 scale. Dashed lines mark the 0.40 and 0.60 verdict thresholds.
function leanBar(t, W) {
  const L = 62, R = 14, H = 92, X = v => L + (v + 1) / 2 * (W - L - R);
  const thr = [-0.2, 0.2].map(v => `<line class="thr" x1="${X(v)}" x2="${X(v)}" y1="14" y2="68"/>`).join("");
  const row = (k, y) => {
    const v = t.lean[k]; if (v == null) return "";
    return `<line class="axis" x1="${X(-1)}" x2="${X(1)}" y1="${y}" y2="${y}"/>
      <text x="${L - 8}" y="${y + 4}" text-anchor="end">${NAME[k]}</text>
      <circle cx="${X(v)}" cy="${y}" r="9" fill="${COLOR[k]}" stroke="#050302" stroke-width="3"/>
      <text class="val" x="${X(v)}" y="${y - 15}" text-anchor="middle">${v > 0 ? "+" : v < 0 ? "−" : ""}${num(Math.abs(v), 2)}</text>`;
  };
  return `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="Lean of each metal from minus one, all weight short, to plus one, all weight long">
    <rect x="${X(-1)}" y="14" width="${X(-0.2) - X(-1)}" height="54" class="zone s"/><rect x="${X(0.2)}" y="14" width="${X(1) - X(0.2)}" height="54" class="zone l"/>
    ${thr}${row("gold", 30)}${row("silver", 54)}
    <text x="${X(-1)}" y="86">all short</text><text x="${X(0)}" y="86" text-anchor="middle">0</text><text x="${X(1)}" y="86" text-anchor="end">all long</text>
  </svg>`;
}

function stat(k, v, c = "") { return `<li><span class="k">${k}</span><span class="v ${c}">${v}</span></li>`; }

export function renderTilt(d) {
  const el = document.getElementById("tilt");
  if (!el) return;
  const t = d.tilt;
  if (!t) { el.innerHTML = `<h2 class="ptitle">Pair check: gold vs silver</h2>${empty("The pair read shows up with the next sweep. The furnace is warming.")}`; return; }
  const r = t.ratio || {};
  const dirWord = t.direction === "higher" ? "a higher ratio" : t.direction === "lower" ? "a lower ratio" : "no change in the ratio";
  el.innerHTML = `
    <h2 class="ptitle">Pair check: gold vs silver</h2>
    <p class="psub">Where the top wallets lean on each metal, side by side, plus the price ratio. Positioning, not a forecast.</p>
    <div class="pair-grid">
      <div class="pair-left">
        ${seesaw(t)}
        <p class="slang pair-head">${esc(t.headline)}</p>
        <p class="slang-sub">${esc(t.text)}</p>
        <div class="chart leanchart" id="lean-chart" role="img" aria-label="Gold and silver lean on one scale"></div>
        <p class="note">Lean is 2 &times; P(long) &minus; 1. Dashed lines are the 0.40 and 0.60 verdict thresholds. By dollars instead of weights the gap is ${num(t.money_gap, 2)} (gold minus silver). As a spread, today's gap points to <b>${dirWord}</b>.</p>
      </div>
      <div class="pair-right">
        <ul class="stats two">
          ${stat("Gold / silver ratio", r.now ? num(r.now, 1) : "–")}
          ${stat("Where that sits, last " + (r.days || 0) + " days", r.pct_rank != null ? Math.round(r.pct_rank * 100) + "th percentile" : "–")}
          ${stat("180-day range", r.min ? `${num(r.min, 1)} to ${num(r.max, 1)}` : "–")}
          ${stat("30-day change", pct(r.change_30d, 1), cls(r.change_30d))}
        </ul>
        <div class="chart" id="ratio-chart" role="img" aria-label="Gold to silver price ratio, daily closes"></div>
        <p class="note">Daily closes of <code>xyz:GOLD</code> over <code>xyz:SILVER</code>; the last point uses the live marks. Dashed line is the window average (${r.mean ? num(r.mean, 1) : "–"}).</p>
      </div>
    </div>`;
  drawTilt(d);
}

export function drawTilt(d) {
  const t = d.tilt; if (!t) return;
  const lc = document.getElementById("lean-chart");
  if (lc && lc.offsetParent) lc.innerHTML = leanBar(t, Math.max(280, lc.clientWidth - 12));
  const rc = document.getElementById("ratio-chart");
  const s = t.ratio?.series || [];
  if (rc && rc.offsetParent) lineChart(rc, {
    series: [{ color: "#EEF1F4", width: 2, points: s }], thresholds: t.ratio?.mean ? [t.ratio.mean] : [],
    yFmt: v => v.toFixed(0), xFmt: v => day(v), xTicks: 4, height: 210, left: 40,
    empty: "No daily history yet for the ratio chart.",
  });
}

/* ---------------------------------------------------------------- crowd check */

function jelly(c) {
  const col = LEVEL_COLOR[c.level] || "var(--flat)";
  const pips = [0, 1, 2, 3].map(i => `<span class="pip ${i < c.score ? "on" : ""} ${c.level === "JELLY" && i < c.score ? "wob" : ""}" style="--c:${col}"></span>`).join("");
  return `<div class="jelly" role="img" aria-label="${c.score} of 4 soft spots: ${c.level}">${pips}</div>`;
}

function shareBar(c) {
  const sh = c.top_shares || [], sd = c.top_sides || [];
  if (!sh.length) return "";
  const rest = Math.max(0, 1 - sh.reduce((a, b) => a + b, 0));
  const seg = sh.map((s, i) => `<span class="seg ${sd[i] || ""}" style="flex:${s}" title="Wallet ${i + 1}: ${pct(s, 1, false)} of the vote (${(sd[i] || "").toLowerCase()})"></span>`).join("");
  return `<div class="sharebar" role="img" aria-label="Share of the vote held by each of the biggest wallets">${seg}<span class="seg rest" style="flex:${rest}" title="All other wallets: ${pct(rest, 1, false)}"></span></div>
    <p class="note sharekey"><span class="dot LONG"></span>long <span class="dot SHORT"></span>short <span class="dot rest"></span>everyone else. Each block is one wallet's slice of the vote.</p>`;
}

const FLAG_TEXT = {
  fragile: ["Flips if 2 or fewer wallets close", "A couple of exits would change the verdict."],
  whale: ["One wallet holds 25% or more of the vote", "One whale decides a quarter of the call."],
  weak_interval: ["95% interval crosses 0.50", "The call is weakly held by the numbers."],
  thin_book: ["Fewer than 20 wallets vote", "A thin book. A handful of bags can swing it."],
};

export function renderCrowd(d) {
  for (const k of METALS) {
    const el = document.getElementById("crowd-" + k);
    if (!el) continue;
    const m = d.metals?.[k], c = m?.crowding;
    const head = `<h2 class="ptitle">Crowd check: ${NAME[k].toLowerCase()}</h2>`;
    if (!c) { el.innerHTML = head + empty("The crowd check shows up with the next sweep."); continue; }
    if (!c.voters) { el.innerHTML = head + empty(`Nobody in the top 500 holds ${NAME[k].toLowerCase()} right now. Nothing to crowd.`); continue; }
    const kTxt = c.k_to_neutral == null ? "–" : c.k_to_neutral === 0 ? "Already neutral" : `${c.k_to_neutral} of ${c.voters}`;
    const kSub = c.k_to_neutral ? `carrying ${pct(c.k_weight_share, 0, false)} of the vote` : "";
    el.innerHTML = `${head}
      <p class="psub">How concentrated the ${NAME[k].toLowerCase()} vote is, and how little it would take to change the call.</p>
      <div class="crowd-top">${jelly(c)}<div><p class="level" style="color:${LEVEL_COLOR[c.level]}">${esc(c.level)}</p><p class="slang-sub">${esc(c.line)}</p></div></div>
      <p class="note flagcount">${c.score} of 4 soft spots</p>
      <ul class="stats two">
        ${stat("Biggest wallet's share of the vote", pct(c.top1_share, 1, false))}
        ${stat("Top 3 / top 5 wallets", `${pct(c.top3_share, 0, false)} / ${pct(c.top5_share, 0, false)}`)}
        ${stat("Like this many equal voters", num(c.effective_voters, 1))}
        ${stat("Wallets that must close to flip the call", kTxt + (kSub ? `<small>${kSub}</small>` : ""))}
      </ul>
      ${shareBar(c)}
      <ul class="flags">${Object.entries(FLAG_TEXT).map(([f, [t, why]]) =>
        `<li class="${c.flags[f] ? "hit" : "ok"}"><span class="mark" aria-hidden="true">${c.flags[f] ? "!" : "·"}</span><span><b>${esc(t)}:</b> ${c.flags[f] ? "yes. " + esc(why) : "no."}</span></li>`).join("")}</ul>
      ${c.exact ? "" : `<p class="note">Estimated from the 20 biggest positions and the side totals. The next sweep stores every voter and this turns exact.</p>`}`;
  }
}

/* ---------------------------------------------------------------- long vs short + last hour */

// Two-sided bar: shorts grow left from the centre line, longs grow right.
function twoSide(label, shortV, longV, fmt, ariaUnit) {
  const tot = (shortV || 0) + (longV || 0);
  const sp = tot > 0 ? shortV / tot : 0.5, lp = tot > 0 ? longV / tot : 0.5;
  return `<div class="twoside" role="img" aria-label="${esc(label)}: ${fmt(shortV)} short, ${fmt(longV)} long ${ariaUnit}">
    <div class="ts-head"><span class="down">${fmt(shortV)} short</span><span class="ts-label">${esc(label)}</span><span class="up">${fmt(longV)} long</span></div>
    <div class="ts-bar"><span class="ts-short" style="flex:${Math.max(sp, 0.0001)}"></span><span class="ts-long" style="flex:${Math.max(lp, 0.0001)}"></span></div>
    <div class="ts-foot"><span>${tot > 0 ? Math.round(sp * 100) : "–"}%</span><span>${tot > 0 ? Math.round(lp * 100) : "–"}%</span></div>
  </div>`;
}

const KIND_WORD = { opened: "opened", added: "added", trimmed: "trimmed", closed: "closed", flipped: "flipped to" };

function hourTable(h) {
  if (!h.items?.length) return "";
  return `<div class="table-wrap"><table class="data compact hourtab"><tr><th>Wallet</th><th>What</th><th class="num">Size</th><th class="num">Seen</th></tr>` +
    h.items.slice(0, 8).map(i => `<tr><td><a class="addr" href="https://app.hyperliquid.xyz/explorer/address/${esc(i.address)}" rel="noopener">${esc(short(i.address))}</a></td>
      <td>${KIND_WORD[i.kind] || esc(i.kind)} <span class="tag ${i.side}">${i.side}</span></td>
      <td class="num ${cls(i.kind === "closed" || i.kind === "trimmed" ? -1 : i.kind === "flipped" ? (i.side === "LONG" ? 1 : -1) : 1)}">${usd(i.usd)}</td>
      <td class="num">${ago(i.seen_ms)}</td></tr>`).join("") + `</table></div>`;
}

export function renderSplit(d) {
  for (const k of METALS) {
    const el = document.getElementById("split-" + k);
    if (!el) continue;
    const m = d.metals?.[k]; if (!m) continue;
    const h = m.hour;
    let body = `<h2 class="ptitle">Long vs short: ${NAME[k].toLowerCase()}</h2>
      <p class="psub">The top 500 wallets that hold ${NAME[k].toLowerCase()} right now, by head count and by dollars.</p>
      ${twoSide("Wallets", m.n_short, m.n_long, v => num(v, 0), "wallets")}
      ${twoSide("USD notional", m.notional_short, m.notional_long, v => usd(v), "")}
      <p class="note">${num(m.n_flat, 0)} of the top 500 hold none and do not vote.</p>
      <h3 class="ptitle sub">Last hour: who did what</h3>`;
    if (!h || !h.available) {
      body += empty(h?.reason || "The last-hour view shows up with the next sweep. The furnace is warming.");
    } else {
      const sn = h.split_now?.long_share, st = h.split_then?.long_share;
      const delta = sn != null && st != null ? (sn - st) * 100 : null;
      body += `<p class="hour-sum">${esc(h.summary)}</p>
        <p class="note hour-split">Long share of the dollars: ${st != null ? pct(st, 0, false) : "–"} to ${sn != null ? pct(sn, 0, false) : "–"}${delta != null ? ` (<span class="${cls(delta)}">${delta > 0 ? "+" : delta < 0 ? "−" : ""}${Math.abs(delta).toFixed(1)} pts</span>)` : ""} over ${h.span_min} minutes, valued at today's price so it counts trades, not price moves.</p>
        ${hourTable(h) || empty("Nobody moved by $1k or more.")}
        <p class="note">${esc(h.resolution_note)}${h.partial ? ` History only reaches back ${h.span_min} minutes so far.` : ""}</p>`;
    }
    el.innerHTML = body;
  }
}

/* ---------------------------------------------------------------- scalp corner */

const LEAN_CLS = { "SCALP LONG": "LONG", "SCALP SHORT": "SHORT", "SIT OUT": "NEUTRAL" };

function partBar(label, v, used) {
  const w = Math.abs(v) * 50;
  return `<div class="part ${used ? "" : "off"}"><span class="pl">${label}</span>
    <span class="pbar" role="img" aria-label="${label} ${used ? v.toFixed(2) : "not used"}"><i class="mid"></i>${used ? `<i class="fill ${v >= 0 ? "up" : "down"}" style="${v >= 0 ? "left:50%" : `right:50%`};width:${w}%"></i>` : ""}</span>
    <span class="pv">${used ? (v > 0 ? "+" : v < 0 ? "−" : "") + Math.abs(v).toFixed(2) : "n/a"}</span></div>`;
}

export function renderScalp(d) {
  const wrap = document.getElementById("scalp");
  if (!wrap) return;
  for (const k of METALS) {
    const el = document.getElementById("scalp-" + k);
    if (!el) continue;
    const s = d.metals?.[k]?.scalp;
    if (!s) { el.innerHTML = `<h3 class="ptitle sub">${NAME[k]}</h3>${empty("The scalp read shows up with the next sweep.")}`; continue; }
    const c = LEAN_CLS[s.lean] || "NEUTRAL";
    el.innerHTML = `<div class="scalp-head"><h3 class="ptitle sub">${NAME[k]}</h3>
        <div class="scalp-stamp ${c}" aria-label="Short-term lean ${esc(s.lean)}, confidence ${esc(s.confidence)}">${esc(s.lean)}</div>
        <span class="conf">confidence: <b>${esc(s.confidence)}</b></span></div>
      <ul class="why">${s.reasons.map(r => `<li>${esc(r)}</li>`).join("")}</ul>
      <div class="parts">${partBar("Wallet flow", s.parts.flow, s.used.flow)}${partBar("1h price", s.parts.momentum, s.used.momentum)}${partBar("Funding fade", s.parts.funding, s.used.funding)}</div>
      <p class="note">1h move ${pct(s.price_move_1h, 2)} &middot; funding ${pct(s.funding_hourly, 4)} an hour &middot; blended score ${num(s.score, 2)} (lean at &plusmn;0.25)${s.window_min ? ` &middot; window ${s.window_min} min` : ""}</p>`;
  }
}

/* ---------------------------------------------------------------- alerts */

const supported = typeof Notification !== "undefined";
let prefs = (() => { try { return parsePrefs(localStorage.getItem(PREF_KEY)); } catch { return parsePrefs(null); } })();
let timer = null, cached = null;
const save = () => { try { localStorage.setItem(PREF_KEY, JSON.stringify(prefs)); } catch { /* private mode */ } };

async function showPing(title, body, tag) {
  const opts = { body, tag, icon: "favicon.svg", badge: "favicon.svg" };
  try {
    const reg = await navigator.serviceWorker?.getRegistration();
    if (reg && reg.showNotification) return reg.showNotification(title, opts);
  } catch { /* fall through */ }
  new Notification(title, opts);
}

async function poll() {
  try {
    const r = await fetch("data/alerts.json", { cache: "no-store" });
    if (!r.ok) return;
    const st = await r.json();
    cached = st;
    for (const e of pickToNotify(st.events, prefs, prefs.lastSeenMs)) await showPing(e.title, e.text, e.id);
    prefs.lastSeenMs = Math.max(prefs.lastSeenMs, newestMs(st.events)); save();
    drawEvents(st);
  } catch (e) { console.error(e); }
}

function startPolling() {
  clearInterval(timer);
  if (prefs.on && supported && Notification.permission === "granted") { poll(); timer = setInterval(poll, 5 * 60e3); }
}

function drawEvents(st) {
  const box = document.getElementById("alert-events"); if (!box) return;
  const ev = [...(st?.events || [])].sort((a, b) => b.ts_utc.localeCompare(a.ts_utc)).slice(0, 8);
  if (!ev.length) { box.innerHTML = empty("No flips logged yet. The furnace is calm."); return; }
  box.innerHTML = `<div class="table-wrap"><table class="data compact"><tr><th>When</th><th>Metal</th><th>What</th><th class="num">P(long)</th><th>Status</th></tr>` +
    ev.map(e => { const t = eventTag(e); return `<tr><td>${when(Date.parse(e.ts_utc))}</td><td>${esc(e.label)}</td>
      <td><span class="tag ${e.from}">${e.from}</span> &rarr; <span class="tag ${e.to}">${e.to}</span></td><td class="num">${p2(e.p_long)}</td>
      <td><span class="tag ${t.cls}" title="${esc(e.reason)}">${t.label}</span></td></tr>`; }).join("") + `</table></div>
    <p class="note">Last update ${st.updated_utc ? ago(Date.parse(st.updated_utc)) : "unknown"}. "Logged only" means the verdict changed but the 95% interval still crosses 0.50, or it moved into NEUTRAL, or it came inside the 3-hour cooldown.</p>`;
}

function drawControls() {
  const perm = supported ? Notification.permission : "unsupported";
  const live = prefs.on && perm === "granted";
  const el = document.getElementById("alert-controls"); if (!el) return;
  el.innerHTML = `
    <div class="chips" role="group" aria-label="Metals to ping about">
      ${METALS.map(k => `<button type="button" data-metal="${k}" aria-pressed="${prefs[k]}">${NAME[k]}</button>`).join("")}
    </div>
    <div class="alert-actions">
      <button type="button" class="goo-btn" id="alert-toggle" ${supported ? "" : "disabled"} aria-pressed="${live}">${live ? "Pings are on. Turn off" : "Turn on pings"}</button>
      <button type="button" class="goo-btn ghost" id="alert-test" ${live ? "" : "disabled"}>Send a test ping</button>
    </div>
    <p class="note" id="alert-status" role="status">${esc(permissionLine(perm, supported))}</p>`;
  el.querySelectorAll("[data-metal]").forEach(b => b.addEventListener("click", () => {
    const k = b.dataset.metal; prefs[k] = !prefs[k]; save(); drawControls();
  }));
  document.getElementById("alert-toggle")?.addEventListener("click", async () => {
    if (live) { prefs.on = false; save(); clearInterval(timer); return drawControls(); }
    const result = Notification.permission === "granted" ? "granted" : await Notification.requestPermission();
    prefs.on = result === "granted";
    if (prefs.on) { prefs.lastSeenMs = Math.max(prefs.lastSeenMs, newestMs(cached?.events), Date.now() - 1); try { await navigator.serviceWorker?.register("sw.js"); } catch { /* optional */ } }
    save(); drawControls(); startPolling();
  });
  document.getElementById("alert-test")?.addEventListener("click", () =>
    showPing("Metal Future Forecast test ping", "If you can read this, flip pings work in this browser. Not financial advice.", "mff-test"));
}

export async function initAlerts(d) {
  drawControls();
  const feeds = d.alerts?.feeds;
  const fl = document.getElementById("alert-feeds");
  if (fl && feeds) fl.innerHTML = [["Gold", feeds.gold], ["Silver", feeds.silver], ["Both", feeds.all]]
    .map(([n, h]) => `<a class="feedlink" href="${esc(h)}" type="application/atom+xml"><span class="rss" aria-hidden="true"></span>${n} feed</a>`).join("") +
    `<a class="feedlink" href="${esc(d.alerts.json)}">alerts.json</a>`;
  try {
    const r = await fetch("data/alerts.json", { cache: "no-store" });
    cached = r.ok ? await r.json() : null;
  } catch { cached = null; }
  drawEvents(cached);
  startPolling();
}


export async function renderHorizonCite() {
  const el = document.getElementById("scalp-bt");
  if (!el) return;
  let cites = null;
  try {
    const r = await fetch("backtest/backtest.json", { cache: "no-store" });
    if (r.ok) cites = oneHourCites(await r.json());
  } catch { /* file not on this copy of the site */ }
  if (!cites) {
    el.innerHTML = `<p class="note">A 1-hour holding test of the <b>main signal</b> (not this scalp lean) lives in <a href="#backtest">Table 5 on the Backtest tab</a>. No hit rate is shown here because those numbers are not in the live files yet, and none will be invented.</p>`;
    return;
  }
  const lines = METALS.map(k => citeLine(cites[k], NAME[k], day)).filter(Boolean);
  el.innerHTML = `<p class="note scalp-cite"><b>Not a backtest of this lean.</b> The figures below are the main signal held for one hour, from Table 5. That study refreshes the call once a day, so it tests timing inside the day, not a faster signal. Hit rate is the share of trades whose direction was right <em>before costs</em>. Average net is after fees and funding. <a href="#backtest">Open Table 5</a>.</p>
    <ul class="why cite">${lines.map(t => `<li>${esc(t)}</li>`).join("")}</ul>`;
}

export function initV2(d) { renderTilt(d); renderCrowd(d); renderSplit(d); renderScalp(d); renderHorizonCite(); initAlerts(d); }
export function redrawV2(d) { drawTilt(d); }
