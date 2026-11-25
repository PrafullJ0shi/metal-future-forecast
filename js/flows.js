import { usd, pct, px, when, esc, short, cls, num } from "./fmt.js";
import { emptyState } from "./app.js";

let D, metal = "gold", tf = null;

function bar(label, v, max, color, right) {
  const w = max > 0 ? Math.max(0, Math.min(100, v / max * 100)) : 0;
  return `<div class="bar-row"><span>${label}</span><span class="bar-track"><span class="bar-fill" style="left:0;width:${w}%;background:${color}"></span></span><span class="num" style="text-align:right">${right ?? usd(v)}</span></div>`;
}

function renderTF(fl) {
  const box = document.getElementById("flow-tf");
  const order = fl?.flow?.order || ["1h", "4h", "8h", "12h", "24h", "48h", "1w"];
  if (!tf) tf = fl?.flow?.default || "4h";
  box.innerHTML = order.map(l => {
    const w = fl?.flow?.windows?.[l]; const ok = !!w?.available;
    return `<button type="button" data-tf="${l}" aria-pressed="${l === tf}" ${ok ? "" : `disabled title="Not enough sweep history for ${l} yet"`}>${l}</button>`;
  }).join("");
}

function render() {
  const m = D.metals[metal], fl = m.flows;
  document.querySelectorAll("#flow-metal button").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.metal === metal)));
  renderTF(fl);
  const fb = document.getElementById("flowbox"), co = document.getElementById("cohorts"), lq = document.getElementById("liqs");
  if (!fl) {
    fb.innerHTML = `<h2 class="ptitle">Past ${tf} in ${esc(m.label)}</h2>` + emptyState("The flow tracker did not run this sweep. Check back after the next pour.");
    co.innerHTML = ""; lq.innerHTML = ""; document.getElementById("whales").innerHTML = ""; return;
  }
  const W = fl.flow.windows[tf] || {}, s = W.smart || {}, c = W.contrast || {};
  const color = metal === "gold" ? "var(--gold-500)" : "var(--silver-300)";
  if (s.available) {
    const max = Math.max(s.longs_in, s.longs_out, s.shorts_in, s.shorts_out, 1);
    fb.innerHTML = `<h2 class="ptitle">Past ${esc(tf)} in ${esc(m.label)}: what the top 500 did</h2>
      <div class="flow-grid">
        <div>
          <p class="headline">${esc(W.smart_headline)}</p>
          <p>${esc(W.smart_sentence)}</p>
          <div class="bars">
            ${bar("Longs in", s.longs_in, max, "var(--up)")}
            ${bar("Longs out", s.longs_out, max, "rgba(123,216,143,.45)")}
            ${bar("Shorts in", s.shorts_in, max, "var(--down)")}
            ${bar("Shorts out", s.shorts_out, max, "rgba(255,107,107,.45)")}
          </div>
        </div>
        <ul class="stats" style="grid-template-columns:1fr 1fr">
          <li><span class="k">Net toward long</span><span class="v ${cls(s.toward_long)}">${usd(s.toward_long)}</span></li>
          <li><span class="k">Price move in window</span><span class="v ${cls(s.move)}">${pct(s.move, 2)}</span></li>
          <li><span class="k">Opened / added longs</span><span class="v">${usd(s.flows.oL)} / ${usd(s.flows.aL)}</span></li>
          <li><span class="k">Opened / added shorts</span><span class="v">${usd(s.flows.oS)} / ${usd(s.flows.aS)}</span></li>
          <li><span class="k">Closed / trimmed longs</span><span class="v">${usd(s.flows.cL)} / ${usd(s.flows.tL)}</span></li>
          <li><span class="k">Closed / trimmed shorts</span><span class="v">${usd(s.flows.cS)} / ${usd(s.flows.tS)}</span></li>
          <li><span class="k">Short share, then → now</span><span class="v">${pct(s.short_share_before, 0, false)} → ${pct(s.short_share_after, 0, false)}</span></li>
          <li><span class="k">Wallets that traded</span><span class="v">${s.wallets_traded}</span></li>
        </ul>
      </div>
      <p class="note">Window measured from ${when(s.base_ms)} to ${when(s.end_ms)} over ${s.steps} sweep step${s.steps === 1 ? "" : "s"}${s.complete ? "" : "; one or more steps were missing, so totals are partial"}.</p>`;
  } else {
    fb.innerHTML = `<h2 class="ptitle">Past ${esc(tf)} in ${esc(m.label)}</h2>` + emptyState((s.reason || "Building history.") + " Patience, wagmi.");
  }

  const cs = fl.cohorts.smart, cc = fl.cohorts.contrast;
  const crow = (lab, f) => `<tr><td class="lbl">${lab}</td><td class="num">${f(cs, s)}</td><td class="num">${f(cc, c)}</td></tr>`;
  co.innerHTML = `<h2 class="ptitle">Top 500 vs the ngmi 500</h2>
    <p class="psub">${esc(W.compare || "")}</p>
    <div class="table-wrap"><table class="data compact"><tr><th></th><th class="num">Top cohort</th><th class="num">Ngmi cohort</th></tr>
    ${crow("Long notional now", x => usd(x.long_ntl))}
    ${crow("Short notional now", x => usd(x.short_ntl))}
    ${crow("Short share of notional", x => pct(x.short_share, 0, false))}
    ${crow("Wallets long / short", x => `${x.n_long ?? "–"} / ${x.n_short ?? "–"}`)}
    ${crow(`Net toward long, past ${esc(tf)}`, (x, w) => w.available ? `<span class="${cls(w.toward_long)}">${usd(w.toward_long)}</span>` : "building")}
    </table></div>
    <p class="note">Top cohort: ${esc(cs.definition)} Ngmi cohort: ${esc(cc.definition)}</p>`;

  const L = fl.liquidations, wave = L.wave || {}, pr = L.oi_proxy || {};
  const st = wave.status || "NO WAVE";
  lq.innerHTML = `<h2 class="ptitle">Liquidations (who got rekt)</h2>
    <p class="psub"><b>Hyperliquid has no market-wide liquidation feed.</b> These are only the liquidations that show up in the fills of the 1,000 wallets we track, so every number here is a floor.</p>
    <p><span class="status ${st.startsWith("PROXY") ? "PROXY" : st === "WAVE" ? "WAVE" : ""}">${esc(st)}</span></p>
    <ul class="stats" style="grid-template-columns:1fr 1fr">
      <li><span class="k">Seen in the last 7 days</span><span class="v">${L.count_7d}</span></li>
      <li><span class="k">Seen notional, 7 days</span><span class="v">${usd(L.usd_7d)}</span></li>
      <li><span class="k">OI change, latest step (proxy)</span><span class="v ${cls(pr.latest?.d_oi)}">${pr.latest ? pct(pr.latest.d_oi, 2) : "–"}</span></li>
      <li><span class="k">Price change, same step</span><span class="v ${cls(pr.latest?.ret)}">${pr.latest ? pct(pr.latest.ret, 2) : "–"}</span></li>
    </ul>
    ${(L.events || []).length ? `<div class="table-wrap"><table class="data compact"><tr><th>When</th><th>Side</th><th class="num">Notional</th><th class="num">Price</th></tr>${L.events.slice(0, 6).map(e => `<tr><td>${when(e.t)}</td><td><span class="tag ${e.side}">${e.side}</span></td><td class="num">${usd(e.ntl)}</td><td class="num">${px(e.px)}</td></tr>`).join("")}</table></div>`
      : emptyState("No liquidations spotted in tracked fills. Nobody got rekt (that we can see).")}
    <p class="note">Proxy rule (not a count): ${esc(pr.rule || "")} ${pr.flagged?.length ? `${pr.flagged.length} step(s) flagged in the last 7 days.` : "No step flagged yet."}</p>`;

  const wr = fl.whale_rules || {};
  document.getElementById("whale-rules").textContent = `Position changes of ${usd(wr.position_usd)}+ between sweeps, single orders of ${usd(wr.order_usd)}+, and worked orders of ${usd(wr.worked_usd)}+ spread over ${wr.worked_orders}+ orders and ${wr.worked_minutes}+ minutes. Top and ngmi cohorts only.`;
  const ws = fl.whales || [];
  document.getElementById("whales").innerHTML = ws.length ? `<ul class="tape">${ws.slice(0, 16).map(whaleRow).join("")}</ul>`
    : emptyState("No whales surfaced yet. Ocean's quiet, ser. The tape fills as sweeps pile up.");
}

function whaleRow(e) {
  const who = `<span class="addr">${short(e.address)}</span> <span class="psub">(${e.cohort === "contrast" ? "ngmi" : "top"} #${e.rank ?? "?"})</span>`;
  let what = "", side = e.side, amt = "";
  if (e.kind === "position") { what = `${esc(e.verb)} ${esc((e.side || "").toLowerCase())}: ${usd(e.before_usd)} → ${usd(e.now_usd)}`; amt = usd(e.change_usd); }
  else if (e.kind === "worked") { what = `worked ${esc(e.method || "order")} ${e.effect ? "(" + esc(e.effect) + ")" : ""}`; amt = usd(e.ntl); }
  else { what = `${e.taker ? "market" : "resting"} order${e.dir ? ", " + esc(e.dir) : ""} at ${px(e.px)}`; amt = usd(e.ntl); }
  return `<li><span class="when">${when(e.t)}</span><span><span class="tag ${side}">${esc(side)}</span></span><span>${who}<br>${what}</span><span class="num"><b>${amt}</b></span></li>`;
}

export function initFlows(d) {
  D = d;
  document.getElementById("flow-metal").addEventListener("click", e => { const b = e.target.closest("button"); if (b) { metal = b.dataset.metal; render(); } });
  document.getElementById("flow-tf").addEventListener("click", e => { const b = e.target.closest("button"); if (b && !b.disabled) { tf = b.dataset.tf; render(); } });
  render();
}
