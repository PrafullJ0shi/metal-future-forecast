// v2 panels: gold-silver pair check, crowd check per metal, opt-in flip alerts.
import { px, pct, num, p2, cls, esc, when, ago, day } from "./fmt.js";
import { lineChart } from "./charts.js";
import { PREF_KEY, parsePrefs, pickToNotify, newestMs, permissionLine, eventTag } from "./alertlogic.js";

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

export function initV2(d) { renderTilt(d); renderCrowd(d); initAlerts(d); }
export function redrawV2(d) { drawTilt(d); }
