import assert from "node:assert/strict";
import { test } from "node:test";
import { parsePrefs, defaultPrefs, pickToNotify, newestMs, permissionLine, eventTag, isPushable } from "../../site/js/alertlogic.js";

const ev = (metal, ts, over = {}) => ({ id: metal + ts, metal, ts_utc: ts, confirmed: true, suppressed: false, ...over });
const on = { on: true, gold: true, silver: true, lastSeenMs: 0 };

test("prefs parse safely", () => {
  assert.deepEqual(parsePrefs("{bad"), defaultPrefs());
  assert.deepEqual(parsePrefs("null"), defaultPrefs());
  assert.equal(parsePrefs('{"on":true,"silver":false,"lastSeenMs":5}').silver, false);
  assert.equal(parsePrefs('{"on":"yes"}').on, false);
  assert.equal(parsePrefs('{"lastSeenMs":"x"}').lastSeenMs, 0);
});

test("only confirmed, unsuppressed, newer, opted-in events ping", () => {
  const events = [
    ev("gold", "2026-11-25T10:00:00Z"),
    ev("gold", "2026-11-25T11:00:00Z", { confirmed: false }),
    ev("gold", "2026-11-25T12:00:00Z", { suppressed: true }),
    ev("silver", "2026-11-25T13:00:00Z"),
    ev("gold", "2026-11-25T14:00:00Z"),
  ];
  const seen = Date.parse("2026-11-25T10:30:00Z");
  const out = pickToNotify(events, on, seen);
  assert.deepEqual(out.map(e => e.ts_utc), ["2026-11-25T13:00:00Z", "2026-11-25T14:00:00Z"]);
  assert.deepEqual(pickToNotify(events, { ...on, silver: false }, seen).map(e => e.metal), ["gold"]);
  assert.deepEqual(pickToNotify(events, { ...on, on: false }, 0), []);
  assert.deepEqual(pickToNotify(null, on, 0), []);
});

test("results are oldest first so pings arrive in order", () => {
  const out = pickToNotify([ev("gold", "2026-11-25T14:00:00Z"), ev("silver", "2026-11-25T09:00:00Z")], on, 0);
  assert.deepEqual(out.map(e => e.metal), ["silver", "gold"]);
});

test("newestMs and tags", () => {
  assert.equal(newestMs([]), 0);
  assert.equal(newestMs([ev("gold", "2026-11-25T10:00:00Z"), ev("gold", "2026-11-25T12:00:00Z")]), Date.parse("2026-11-25T12:00:00Z"));
  assert.equal(eventTag(ev("gold", "2026-11-25T10:00:00Z")).label, "ping");
  assert.equal(eventTag(ev("gold", "x", { suppressed: true })).label, "cooldown");
  assert.equal(eventTag(ev("gold", "x", { confirmed: false })).label, "logged only");
  assert.equal(isPushable(undefined), false);
});

test("permission copy covers every state", () => {
  assert.match(permissionLine("default", false), /Atom feeds/);
  assert.match(permissionLine("denied", true), /blocked/);
  assert.match(permissionLine("granted", true), /while this page is open/);
  assert.match(permissionLine("default", true), /off until/);
});
