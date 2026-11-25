"""Rebuild P(long) for GOLD and SILVER from the cohort's position history and test it against baselines.

Deterministic: reads research/backtest/data/inputs/ (committed) and writes CSVs and JSON to
research/backtest/data/ plus the site's site/backtest/backtest.json.

Rules (fixed before looking at metal results; inherited from the BTC project):
  * weights and P(long): identical to the live signal, with today's month PnL and equity
  * verdict: LONG at p >= 0.60, SHORT at p <= 0.40, else flat
  * information: the signal for UTC day D uses each wallet's average position over day D-1
    (Hyperliquid serves older positions only as daily aggregates), so it refreshes at 00:00 UTC
  * one unit of notional, no leverage, no slippage; taker fee on every position change
    (xyz:GOLD 0.09%, xyz:SILVER 0.009%); funding paid or received every hour held
  * two price grids: hourly bars where 1h candles exist (the latest 5,000), daily bars since listing
"""

from __future__ import annotations

import csv
import json
import math
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from app import config  # noqa: E402
from app.signal import equity_shrink, skill_weight  # noqa: E402

BT = ROOT / "research" / "backtest"
INP = BT / "data" / "inputs"
OUT = BT / "data"
SITE = ROOT / "site" / "backtest"
H = 3_600_000
DAY = 86_400_000
REGIME_Z = 0.5      # trailing 7-day return / (bar vol * sqrt(bars in 7 days)) beyond +-0.5 = up / down
GRID = [(0.55, 0.45), (0.60, 0.40), (0.65, 0.35), (0.70, 0.30), (0.75, 0.25)]
STRATS = ["signal", "long_only", "short_only", "fade", "hold", "short"]
GRIDS = {"hourly": {"step": H, "per_year": 24 * 365, "week": 168},
         "daily": {"step": DAY, "per_year": 365, "week": 7}}


def load():
    return (json.loads((INP / "market.json").read_text()), json.loads((INP / "wallets.json").read_text()),
            json.loads((INP / "wallet_paths.json").read_text()))


def voter_weights(wallets, paths):
    """Static part of each wallet's weight (skill x equity shrink); unknown wallets flagged."""
    out = []
    for w in wallets:
        base = skill_weight(w["month_pnl"] or 0) * equity_shrink(w["equity"])
        p = paths.get(w["address"])
        out.append({"w": w, "base": base, "known": p is not None, "days": p["days"] if p else None})
    return out


def daily_p(voters, metal, day_starts, day_open):
    """P(long) for each UTC day D from positions averaged over D-1, priced at D's open."""
    pot_all = sum(v["base"] for v in voters)
    pot_known = sum(v["base"] for v in voters if v["known"])
    rows = {}
    for D in day_starts:
        prev = str(D - DAY)
        B = day_open[D]
        wl = ws = 0.0
        nl = ns = 0
        for v in voters:
            if not v["known"]:
                continue
            q = v["days"][metal].get(prev)
            if not q:
                continue
            E = v["w"]["equity"]
            wt = v["base"] * (min(3.0, abs(q) * B / E) if E > 0 else 0.0)
            if q > 0:
                wl += wt; nl += 1
            else:
                ws += wt; ns += 1
        rows[D] = {"p": wl / (wl + ws) if wl + ws > 0 else None, "n_long": nl, "n_short": ns,
                   "w_long": wl, "w_short": ws}
    return rows, (pot_known / pot_all if pot_all else 0.0)


def sigma(p, hi=config.P_LONG_THRESHOLD, lo=config.P_SHORT_THRESHOLD):
    if p is None:
        return 0
    return 1 if p >= hi else (-1 if p <= lo else 0)


def run(pos_seq, rets, fund, fee):
    out, prev = [], 0
    for i, s in enumerate(pos_seq):
        f = fee * abs(s - prev)
        fu = -s * fund[i]
        g = s * rets[i]
        out.append({"pos": s, "gross": g, "fee": f, "funding": fu, "net": g - f + fu})
        prev = s
    return out


def stats(rows, rets, per_year):
    if not rows:
        return None
    nets = [r["net"] for r in rows]
    eq, peak, mdd = 1.0, 1.0, 0.0
    for x in nets:
        eq *= 1 + x
        peak = max(peak, eq)
        mdd = min(mdd, eq / peak - 1)
    inm = [i for i, r in enumerate(rows) if r["pos"] != 0]
    hits = sum(1 for i in inm if rows[i]["pos"] * rets[i] > 0)
    sd = statistics.pstdev(nets) if len(nets) > 1 else 0.0
    trades = sum(1 for i, r in enumerate(rows) if r["pos"] != (rows[i - 1]["pos"] if i else 0))
    eps, cur, acc = [], None, 1.0
    for r in rows:
        if r["pos"] != cur:
            if cur not in (None, 0):
                eps.append(acc - 1)
            cur, acc = r["pos"], 1.0
        acc *= 1 + r["net"]
    if cur not in (None, 0):
        eps.append(acc - 1)
    return {
        "bars": len(rows),
        "total_return": eq - 1,
        "max_drawdown": mdd,
        "sharpe_like": (statistics.fmean(nets) / sd * math.sqrt(per_year)) if sd > 0 else None,
        "hit_rate": hits / len(inm) if inm else None,
        "avg_return_per_bar_in_market": (sum(rows[i]["net"] for i in inm) / len(inm)) if inm else None,
        "time_in_market": len(inm) / len(rows),
        "bars_long": sum(1 for r in rows if r["pos"] > 0),
        "bars_short": sum(1 for r in rows if r["pos"] < 0),
        "trades": trades,
        "fees": -sum(r["fee"] for r in rows),
        "funding": sum(r["funding"] for r in rows),
        "episodes": len(eps),
        "avg_return_per_episode": statistics.fmean(eps) if eps else None,
        "episode_win_rate": (sum(1 for e in eps if e > 0) / len(eps)) if eps else None,
    }


def curve(rows):
    eq, out = 1.0, []
    for r in rows:
        eq *= 1 + r["net"]
        out.append(eq - 1)
    return out


def regimes(opens, week):
    lr = [0.0] + [math.log(opens[i] / opens[i - 1]) for i in range(1, len(opens))]
    out = []
    for i in range(len(opens)):
        if i < week:
            out.append(None)
            continue
        sd = statistics.pstdev(lr[i - week + 1:i + 1])
        z = math.log(opens[i] / opens[i - week]) / (sd * math.sqrt(week)) if sd > 0 else 0.0
        out.append("up" if z > REGIME_Z else ("down" if z < -REGIME_Z else "sideways"))
    return out


def strat_positions(ps, hi=config.P_LONG_THRESHOLD, lo=config.P_SHORT_THRESHOLD):
    sig = [sigma(p, hi, lo) for p in ps]
    return {"signal": sig, "long_only": [max(0, s) for s in sig], "short_only": [min(0, s) for s in sig],
            "fade": [-s for s in sig], "hold": [1] * len(ps), "short": [-1] * len(ps)}


def evaluate(gname, times, opens_n, fund, ps, fee, cohort_ms, P_rows):
    """All windows, regimes, stress and the threshold grid on one price grid."""
    g = GRIDS[gname]
    n = len(times)
    rets = [opens_n[i + 1] / opens_n[i] - 1 for i in range(n)]
    opens = opens_n[:-1]
    S = strat_positions(ps)
    reg = regimes(opens, g["week"])
    first = next((i for i, p in enumerate(ps) if p is not None), n)
    month = 30 * DAY // g["step"]
    in_month = next((i for i, t in enumerate(times) if t >= cohort_ms - 30 * DAY), n)
    wins = {}
    if gname == "hourly":
        wins["30d"] = (max(first, n - month), n, "yes")
        wins["90d"] = (max(first, n - 3 * month), n, "partial")
        wins["max_h"] = (first, n, "partial")
        wins["oos_h"] = (first, in_month, "no")
    else:
        wins["listing"] = (first, n, "partial")
        wins["oos_d"] = (first, in_month, "no")
    res = {"windows": {}, "regime_labels": reg}
    for wname, (i0, i1, ins) in wins.items():
        sl = slice(i0, i1)
        r_ = rets[sl]
        wres = {"grid": gname, "start_ms": times[i0], "end_ms": times[i1 - 1] + g["step"], "bars": i1 - i0,
                "in_sample": ins, "metal_return": opens_n[i1] / opens_n[i0] - 1, "strategies": {}, "regimes": {},
                "stress": {}}
        for k in STRATS:
            wres["strategies"][k] = stats(run(S[k][sl], r_, fund[sl], fee), r_, g["per_year"])
        for lab, f2 in (("fee_x2", fee * 2), ("standard_hip3_fee", 0.0009)):
            wres["stress"][lab] = stats(run(S["signal"][sl], r_, fund[sl], f2), r_, g["per_year"])["total_return"]
        rows_all = {k: run(S[k], rets, fund, fee) for k in ("signal", "hold", "short")}
        for rg in ("up", "down", "sideways"):
            idx = [i for i in range(i0, i1) if reg[i] == rg]
            if not idx:
                wres["regimes"][rg] = None
                continue
            out = {"bars": len(idx), "metal_move": math.prod(1 + rets[i] for i in idx) - 1}
            for k, ra in rows_all.items():
                rr = [ra[i] for i in idx]
                inm = [(x, i) for x, i in zip(rr, idx) if x["pos"] != 0]
                out[k] = {"return": math.prod(1 + x["net"] for x in rr) - 1,
                          "hit_rate": (sum(1 for x, i in inm if x["pos"] * rets[i] > 0) / len(inm)) if inm else None,
                          "time_in_market": len(inm) / len(rr)}
            sg = [S["signal"][i] for i in idx]
            out["share_long"] = sum(1 for s in sg if s > 0) / len(idx)
            out["share_short"] = sum(1 for s in sg if s < 0) / len(idx)
            wres["regimes"][rg] = out
        res["windows"][wname] = wres
    # Threshold grid: tune on the first half of the out-of-sample span, test on the second half.
    i0, i1 = first, in_month
    mid = i0 + (i1 - i0) // 2
    grid = []
    for hi, lo in GRID:
        Sg = strat_positions(ps, hi, lo)["signal"]
        part = lambda a, b: stats(run(Sg[a:b], rets[a:b], fund[a:b], fee), rets[a:b], g["per_year"])  # noqa: E731
        grid.append({"long": hi, "short": lo, "live": (hi, lo) == (config.P_LONG_THRESHOLD, config.P_SHORT_THRESHOLD),
                     "tune": part(i0, mid), "test": part(mid, i1), "full": part(i0, n)})
    best = max(grid, key=lambda r: (r["tune"]["sharpe_like"] if r["tune"]["sharpe_like"] is not None else -1e9))
    res["grid"] = {"grid": gname, "tune_start_ms": times[i0], "split_ms": times[mid], "end_ms": times[i1 - 1] + g["step"],
                   "rows": grid, "best_on_tune": [best["long"], best["short"]]}
    res["curves"] = {k: [round(x, 5) for x in curve(run(S[k][first:], rets[first:], fund[first:], fee))] for k in STRATS}
    res["first"] = first
    res["rets"], res["S"], res["opens"] = rets, S, opens
    return res


def main():
    mk, wl, paths = load()
    wallets = [w for w in wl["wallets"] if (w.get("equity") or 0) > 0]
    voters = voter_weights(wallets, paths)
    cohort_ms = int(__import__("datetime").datetime.fromisoformat(wl["cohort_built_at_utc"].replace("Z", "+00:00")).timestamp() * 1000)
    rules = {"thresholds": [config.P_LONG_THRESHOLD, config.P_SHORT_THRESHOLD], "regime_z": REGIME_Z, "grid": GRID,
             "information": "day D trades on each wallet's average position over day D-1 (refresh 00:00 UTC)",
             "unit": "1x notional, no leverage, no slippage", "cohort_built_ms": cohort_ms}
    result = {"rules": rules, "metals": {}}
    site = {"rules": rules, "metals": {}}
    for metal, m in config.METALS.items():
        coin, fee = m["coin"], m["taker_fee"]
        C = mk["coins"][coin]
        fmap = {}
        for t, r in C["funding"]:
            fmap[t - t % H] = r
        # Daily P(long), keyed by UTC day start.
        d_times_all = [r[0] for r in C["c1d"]]
        d_open = {r[0]: r[1] for r in C["c1d"]}
        h_open = {r[0]: r[1] for r in C["c1h"]}
        P, known_share = daily_p(voters, metal, d_times_all, d_open)

        # Hourly grid. Funding stamped at the end of hour i is paid by the position held during hour i.
        ht = [r[0] for r in C["c1h"]]
        h_opens = [r[1] for r in C["c1h"]]
        ht_n = ht[:-1]
        h_fund = [fmap.get(t + H, 0.0) for t in ht_n]
        h_ps = [P.get(t - t % DAY, {}).get("p") for t in ht_n]
        hres = evaluate("hourly", ht_n, h_opens, h_fund, h_ps, fee, cohort_ms, P)

        # Daily grid since listing: return open-to-open, funding summed over the day's 24 hours.
        dt_n = d_times_all[:-1]
        d_opens = [d_open[t] for t in d_times_all]
        d_fund = [sum(fmap.get(t + k * H, 0.0) for k in range(1, 25)) for t in dt_n]
        d_ps = [P[t]["p"] for t in dt_n]
        dres = evaluate("daily", dt_n, d_opens, d_fund, d_ps, fee, cohort_ms, P)

        windows = {**hres["windows"], **dres["windows"]}
        summary = {"coin": coin, "taker_fee": fee, "known_weight_share": known_share, "windows": windows,
                   "grids": {"hourly": hres["grid"], "daily": dres["grid"]},
                   "hourly_from_ms": ht_n[hres["first"]], "daily_from_ms": dt_n[dres["first"]]}
        sig_d = dres["S"]["signal"][dres["first"]:]
        summary["signal_mix"] = {"long": sig_d.count(1) / len(sig_d), "short": sig_d.count(-1) / len(sig_d),
                                 "flat": sig_d.count(0) / len(sig_d)}
        vot = [P[t]["n_long"] + P[t]["n_short"] for t in dt_n[dres["first"]:]]
        summary["voters"] = {"min": min(vot), "median": statistics.median(vot), "max": max(vot)}
        result["metals"][metal] = summary

        # CSVs.
        with (OUT / f"daily_{metal}.csv").open("w", newline="") as f:
            wr = csv.writer(f)
            wr.writerow(["day_utc", "open", "p_long", "signal", "voters_long", "voters_short", "weight_long", "weight_short",
                         "regime", "funding_day", "next_day_return", "signal_net_return"])
            rows_sig = run(dres["S"]["signal"], dres["rets"], d_fund, fee)
            for i, t in enumerate(dt_n):
                r = P[t]
                wr.writerow([iso(t)[:10], d_opens[i], "" if r["p"] is None else round(r["p"], 4), dres["S"]["signal"][i],
                             r["n_long"], r["n_short"], round(r["w_long"], 4), round(r["w_short"], 4),
                             dres["regime_labels"][i] or "", round(d_fund[i], 8), round(dres["rets"][i], 6),
                             round(rows_sig[i]["net"], 6)])
        with (OUT / f"hourly_{metal}.csv").open("w", newline="") as f:
            wr = csv.writer(f)
            wr.writerow(["time_utc", "open", "p_long", "signal", "regime", "funding_rate", "next_hour_return", "signal_net_return"])
            rows_sig = run(hres["S"]["signal"], hres["rets"], h_fund, fee)
            for i, t in enumerate(ht_n):
                wr.writerow([iso(t), h_opens[i], "" if h_ps[i] is None else round(h_ps[i], 4), hres["S"]["signal"][i],
                             hres["regime_labels"][i] or "", h_fund[i], round(hres["rets"][i], 6), round(rows_sig[i]["net"], 6)])

        def ser(res, times, ps, step_max=1400):
            f0 = res["first"]
            t = times[f0:]
            step = max(1, math.ceil(len(t) / step_max))
            return {"step": step, "t": t[::step], "p": [None if p is None else round(p, 4) for p in ps[f0:]][::step],
                    "price": res["opens"][f0:][::step], "curves": {k: v[::step] for k, v in res["curves"].items()}}
        dser = ser(dres, dt_n, d_ps)
        dser["voters_long"] = [P[t]["n_long"] for t in dser["t"]]
        dser["voters_short"] = [P[t]["n_short"] for t in dser["t"]]
        site["metals"][metal] = {"summary": summary, "series": {"hourly": ser(hres, ht_n, h_ps), "daily": dser}}

    with (OUT / "strategies.csv").open("w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["metal", "window", "bars", "bar", "in_sample", "strategy", "total_return", "max_drawdown", "sharpe_like",
                     "hit_rate", "avg_return_per_bar_in_market", "time_in_market", "trades", "fees", "funding", "episodes",
                     "avg_return_per_episode", "episode_win_rate"])
        for metal, s in result["metals"].items():
            for wn, w in s["windows"].items():
                for k in STRATS:
                    x = w["strategies"][k]
                    wr.writerow([metal, wn, w["bars"], w["grid"], w["in_sample"], k, r6(x["total_return"]), r6(x["max_drawdown"]),
                                 r6(x["sharpe_like"]), r6(x["hit_rate"]), r6(x["avg_return_per_bar_in_market"]),
                                 r6(x["time_in_market"]), x["trades"], r6(x["fees"]), r6(x["funding"]), x["episodes"],
                                 r6(x["avg_return_per_episode"]), r6(x["episode_win_rate"])])
    with (OUT / "threshold_grid.csv").open("w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["metal", "bar", "long_threshold", "short_threshold", "live", "best_on_tune", "segment", "total_return",
                     "sharpe_like", "max_drawdown", "time_in_market", "trades"])
        for metal, s in result["metals"].items():
            for gname, gg in s["grids"].items():
                for r in gg["rows"]:
                    for seg in ("tune", "test", "full"):
                        x = r[seg]
                        wr.writerow([metal, gname, r["long"], r["short"], r["live"], [r["long"], r["short"]] == gg["best_on_tune"],
                                     seg, r6(x["total_return"]), r6(x["sharpe_like"]), r6(x["max_drawdown"]),
                                     r6(x["time_in_market"]), x["trades"]])
    with (OUT / "regimes.csv").open("w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["metal", "window", "regime", "bars", "metal_move", "signal_return", "signal_hit_rate",
                     "signal_time_in_market", "hold_return", "short_return", "share_long_calls", "share_short_calls"])
        for metal, s in result["metals"].items():
            for wn, w in s["windows"].items():
                for g, r in w["regimes"].items():
                    if r:
                        wr.writerow([metal, wn, g, r["bars"], r6(r["metal_move"]), r6(r["signal"]["return"]),
                                     r6(r["signal"]["hit_rate"]), r6(r["signal"]["time_in_market"]), r6(r["hold"]["return"]),
                                     r6(r["short"]["return"]), r6(r["share_long"]), r6(r["share_short"])])
    result["inputs"] = json.loads((INP / "reach.json").read_text())
    site["inputs"] = result["inputs"]
    (OUT / "summary.json").write_text(json.dumps(result, indent=1))
    SITE.mkdir(parents=True, exist_ok=True)
    (SITE / "backtest.json").write_text(json.dumps(site, separators=(",", ":")))
    return result


def r6(x):
    return "" if x is None else round(x, 6)


def iso(ms):
    import datetime as dt
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


if __name__ == "__main__":
    r = main()
    for metal, m in r["metals"].items():
        print(metal, "known weight", round(m["known_weight_share"], 3), m["signal_mix"], m["voters"])
        for wn, w in m["windows"].items():
            s = w["strategies"]
            print(f"  {wn:8s} {iso(w['start_ms'])[:10]}..{iso(w['end_ms'])[:10]} ins={w['in_sample']:7s} signal {s['signal']['total_return']:+.2%} "
                  f"(sh {s['signal']['sharpe_like'] or 0:.2f}, in mkt {s['signal']['time_in_market']:.0%}) hold {s['hold']['total_return']:+.2%} "
                  f"short {s['short']['total_return']:+.2%} metal {w['metal_return']:+.2%}")
        print("  best on tune", m["grids"]["hourly"]["best_on_tune"], m["grids"]["daily"]["best_on_tune"])
