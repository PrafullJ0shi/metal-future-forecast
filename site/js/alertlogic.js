// Pure helpers for the opt-in browser pings. No DOM, no network: tested with node.
export const PREF_KEY = "mff.alerts.v1";
export const METALS = ["gold", "silver"];

export function defaultPrefs() { return { on: false, gold: true, silver: true, lastSeenMs: 0 }; }

export function parsePrefs(text) {
  const base = defaultPrefs();
  try {
    const p = JSON.parse(text);
    if (!p || typeof p !== "object") return base;
    return {
      on: p.on === true,
      gold: p.gold !== false,
      silver: p.silver !== false,
      lastSeenMs: Number.isFinite(p.lastSeenMs) ? p.lastSeenMs : 0,
    };
  } catch { return base; }
}

// A ping is a confirmed, unsuppressed flip that is newer than what this browser has already seen
// and is for a metal the reader switched on.
export function isPushable(e) { return !!e && e.confirmed === true && e.suppressed !== true; }

export function pickToNotify(events, prefs, lastSeenMs) {
  if (!prefs || !prefs.on || !Array.isArray(events)) return [];
  return events
    .filter(e => isPushable(e) && prefs[e.metal] === true && Date.parse(e.ts_utc) > lastSeenMs)
    .sort((a, b) => Date.parse(a.ts_utc) - Date.parse(b.ts_utc));
}

export function newestMs(events) {
  return (events || []).reduce((m, e) => Math.max(m, Date.parse(e.ts_utc) || 0), 0);
}

export function permissionLine(permission, supported) {
  if (!supported) return "This browser has no notification support. Use the Atom feeds instead.";
  if (permission === "denied") return "Notifications are blocked for this site. Allow them in the browser's site settings, then turn pings on again.";
  if (permission === "granted") return "Pings are allowed. They fire only while this page is open in a tab.";
  return "Pings are off until you switch them on and allow notifications.";
}

export function eventTag(e) {
  if (isPushable(e)) return { label: "ping", cls: "is" };
  if (e.suppressed) return { label: "cooldown", cls: "oos" };
  return { label: "logged only", cls: "oos" };
}
