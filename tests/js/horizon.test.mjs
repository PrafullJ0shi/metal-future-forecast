import assert from "node:assert/strict";
import { test } from "node:test";
import { oneHourRow, oneHourCites, citeLine } from "../../site/js/horizon.js";

const row = { hours: 1, signal: { trades: 3755, hit_rate: 0.4990679, avg_net: -0.00175819 } };
const bt = {
  metals: {
    gold: { summary: { horizons: { hourly: { max_h: { "1h": row } } }, windows: { max_h: { start_ms: 1777600800000, end_ms: 1795611600000 } }, hourly_from_ms: 1777600800000 } },
    silver: { summary: { horizons: { hourly: { max_h: { "1h": { hours: 1, signal: { trades: 3837, hit_rate: 0.4910086, avg_net: -0.00015595 } } } } }, windows: { max_h: { start_ms: 1777600800000, end_ms: 1795611600000 } } } },
  },
};

test("reads the 1h row of the longest hourly window and nothing else", () => {
  const g = oneHourRow(bt, "gold");
  assert.equal(g.trades, 3755);
  assert.equal(g.hit_rate, 0.4990679);
  assert.equal(g.avg_net, -0.00175819);
  assert.equal(g.start_ms, 1777600800000);
  assert.equal(g.end_ms, 1795611600000);
});

test("returns null when the 1h row or a required field is missing — never invents", () => {
  assert.equal(oneHourRow(null, "gold"), null);
  assert.equal(oneHourRow({}, "gold"), null);
  assert.equal(oneHourRow({ metals: { gold: { summary: {} } } }, "gold"), null);
  const missingNet = JSON.parse(JSON.stringify(bt));
  delete missingNet.metals.gold.summary.horizons.hourly.max_h["1h"].signal.avg_net;
  assert.equal(oneHourRow(missingNet, "gold"), null);
  assert.equal(oneHourCites({ metals: {} }), null);
});

test("collects both metals or just the one that has a row", () => {
  const all = oneHourCites(bt);
  assert.equal(all.gold.trades, 3755);
  assert.equal(all.silver.trades, 3837);
  const onlyG = oneHourCites({ metals: { gold: bt.metals.gold } });
  assert.ok(onlyG.gold && !onlyG.silver);
});

test("cite line spells out before-costs hit rate and after-costs net, no invented hit rate", () => {
  const line = citeLine(oneHourRow(bt, "gold"), "Gold", () => "1 May 2026");
  assert.match(line, /3,755 one-hour trades/);
  assert.match(line, /hit rate 49\.9% before costs/);
  assert.match(line, /average net −17\.6 bp \(loses money after costs\)/);
  assert.match(line, /1 May 2026 to 1 May 2026/);
  assert.equal(citeLine(null, "Gold"), null);
});
