// Number and time formatting. Times are shown in the reader's own time zone, labelled.
export const nf = (d = 0) => new Intl.NumberFormat("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
export function usd(x, compact = true) {
  if (x == null || !isFinite(x)) return "–";
  const a = Math.abs(x), s = x < 0 ? "−" : "";
  if (!compact) return s + "$" + nf(a >= 100 ? 0 : 2).format(a);
  if (a >= 1e9) return s + "$" + nf(2).format(a / 1e9) + "B";
  if (a >= 1e6) return s + "$" + nf(2).format(a / 1e6) + "M";
  if (a >= 1e3) return s + "$" + nf(a % 1000 === 0 ? 0 : 1).format(a / 1e3) + "k";
  return s + "$" + nf(0).format(a);
}
export function px(x) {
  if (x == null || !isFinite(x)) return "–";
  return "$" + nf(x >= 1000 ? 1 : x >= 100 ? 2 : 3).format(x);
}
export function pct(x, d = 1, sign = true) {
  if (x == null || !isFinite(x)) return "–";
  const v = x * 100, s = v > 0 && sign ? "+" : v < 0 ? "−" : "";
  return s + nf(d).format(Math.abs(v)) + "%";
}
export function num(x, d = 2) { return x == null || !isFinite(x) ? "–" : (x < 0 ? "−" : "") + nf(d).format(Math.abs(x)); }
export function p2(x) { return x == null ? "–" : nf(2).format(x); }
export function cls(x) { return x == null ? "" : x > 0 ? "up" : x < 0 ? "down" : "flat"; }
const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
const tzShort = (() => {
  try { return new Intl.DateTimeFormat("en-US", { timeZoneName: "short" }).formatToParts(new Date()).find(p => p.type === "timeZoneName").value; }
  catch { return tz; }
})();
export function when(ms, withDate = true) {
  if (!ms) return "–";
  const d = new Date(ms);
  const opt = withDate ? { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", hour12: false } : { hour: "2-digit", minute: "2-digit", hour12: false };
  return new Intl.DateTimeFormat("en-GB", opt).format(d) + " " + tzShort;
}
export function day(ms) { return new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short" }).format(new Date(ms)); }
export function ago(ms) {
  const m = Math.round((Date.now() - ms) / 60000);
  if (m < 1) return "just now";
  if (m < 60) return m + " min ago";
  const h = Math.round(m / 60);
  return h < 48 ? h + " h ago" : Math.round(h / 24) + " days ago";
}
export const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
export const short = a => a ? a.slice(0, 6) + "…" + a.slice(-4) : "–";
export const tzLabel = tzShort;
