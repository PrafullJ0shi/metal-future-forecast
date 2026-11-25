// Plain SVG charts: hairline grid, no gradients, no animation. Sized to the container.
import { esc } from "./fmt.js";

function ticks(lo, hi, n = 5) {
  const span = hi - lo || 1, step0 = span / n, mag = Math.pow(10, Math.floor(Math.log10(step0)));
  const step = [1, 2, 2.5, 5, 10].map(m => m * mag).find(s => s >= step0) || step0;
  const out = []; for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(+v.toFixed(10));
  return out;
}

export function lineChart(el, opts) {
  const W = Math.max(280, el.clientWidth - 12), H = opts.height || (W < 500 ? 220 : 260);
  const m = { l: opts.left ?? 46, r: 14, t: 12, b: 26 };
  const series = opts.series.filter(s => s.points && s.points.length);
  if (!series.length) {
    el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}"><text class="empty" x="${W / 2}" y="${H / 2}" text-anchor="middle">${esc(opts.empty || "Nothing to plot yet. Building history, wagmi.")}</text></svg>`;
    return;
  }
  let xs = series.flatMap(s => s.points.map(p => p[0])), ys = series.flatMap(s => s.points.map(p => p[1])).filter(v => v != null && isFinite(v));
  let x0 = Math.min(...xs), x1 = Math.max(...xs);
  if (x0 === x1) { x0 -= 3600e3; x1 += 3600e3; }
  let [y0, y1] = opts.yDomain || [Math.min(...ys), Math.max(...ys)];
  if (!opts.yDomain) { const pad = (y1 - y0) * 0.08 || Math.abs(y1) * 0.01 || 1; y0 -= pad; y1 += pad; }
  const X = v => m.l + (v - x0) / (x1 - x0) * (W - m.l - m.r);
  const Y = v => m.t + (1 - (v - y0) / (y1 - y0)) * (H - m.t - m.b);
  let g = "";
  for (const v of (opts.yTicks || ticks(y0, y1, 4))) {
    if (v < y0 || v > y1) continue;
    g += `<line class="grid" x1="${m.l}" x2="${W - m.r}" y1="${Y(v)}" y2="${Y(v)}"/><text x="${m.l - 6}" y="${Y(v) + 4}" text-anchor="end">${esc((opts.yFmt || String)(v))}</text>`;
  }
  const nx = Math.min(opts.xTicks || 6, W < 500 ? 3 : 6);
  for (let i = 0; i <= nx; i++) {
    const v = x0 + (x1 - x0) * i / nx;
    g += `<text x="${X(v)}" y="${H - 6}" text-anchor="${i === 0 ? "start" : i === nx ? "end" : "middle"}">${esc((opts.xFmt || String)(v))}</text>`;
  }
  for (const t of opts.thresholds || []) if (t >= y0 && t <= y1) g += `<line class="thr" x1="${m.l}" x2="${W - m.r}" y1="${Y(t)}" y2="${Y(t)}"/>`;
  for (const b of opts.bands || []) {
    g += `<rect x="${X(b[0])}" y="${m.t}" width="${Math.max(1, X(b[1]) - X(b[0]))}" height="${H - m.t - m.b}" fill="${b[2]}" />`;
  }
  g += `<line class="axis" x1="${m.l}" x2="${W - m.r}" y1="${H - m.b}" y2="${H - m.b}"/>`;
  for (const s of series) {
    let d = "", pen = false;
    for (const [x, y] of s.points) {
      if (y == null || !isFinite(y)) { pen = false; continue; }
      d += (pen ? "L" : "M") + X(x).toFixed(1) + " " + Y(y).toFixed(1); pen = true;
    }
    g += `<path d="${d}" fill="none" stroke="${s.color}" stroke-width="${s.width || 2}" ${s.dash ? `stroke-dasharray="${s.dash}"` : ""} stroke-linejoin="round" stroke-linecap="round"/>`;
    if (s.dots) for (const [x, y] of s.points) if (y != null) g += `<circle cx="${X(x)}" cy="${Y(y)}" r="2.6" fill="${s.color}"/>`;
    if (s.label) { const lp = s.points[s.points.length - 1]; }
  }
  el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}">${g}</svg>`;
}

export function gauge(W, p, lo, hi, color) {
  W = Math.max(260, Math.round(W)); const H = 70, L = 14, R = W - 14, y = 28, X = v => L + v * (R - L);
  let s = `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" aria-hidden="true">`;
  s += `<rect x="${X(0)}" y="${y - 9}" width="${X(.4) - X(0)}" height="18" rx="9" fill="rgba(255,107,107,.28)"/>`;
  s += `<rect x="${X(.4)}" y="${y - 9}" width="${X(.6) - X(.4)}" height="18" fill="rgba(185,166,140,.25)"/>`;
  s += `<rect x="${X(.6)}" y="${y - 9}" width="${X(1) - X(.6)}" height="18" rx="9" fill="rgba(123,216,143,.28)"/>`;
  s += `<rect x="${X(0)}" y="${y - 9}" width="${X(1) - X(0)}" height="18" rx="9" fill="none" stroke="#050302" stroke-width="3"/>`;
  if (lo != null && hi != null) s += `<rect x="${X(lo)}" y="${y - 5}" width="${Math.max(2, X(hi) - X(lo))}" height="10" rx="5" fill="${color}" opacity=".55"/>`;
  if (p != null) s += `<circle cx="${X(p)}" cy="${y}" r="12" fill="${color}" stroke="#050302" stroke-width="3"/>`;
  const marks = W < 420 ? [[0, "0"], [.4, "0.40"], [.6, "0.60"], [1, "1"]] : [[0, "0"], [.4, "0.40"], [.5, "0.50"], [.6, "0.60"], [1, "1"]];
  for (const [v, t] of marks)
    s += `<text x="${X(v)}" y="${y + 34}" text-anchor="${v === 0 ? "start" : v === 1 ? "end" : "middle"}" font-size="13" fill="#8A9299" font-family="Nunito, sans-serif">${t}</text>`;
  return s + "</svg>";
}
