#!/usr/bin/env python3
"""Five-year Shahin-FX optimisation on EURUSD, GBPUSD, USDJPY (shared account).

Stage 1  full grid (timeframe, Ichimoku preset, Donchian, ATR stop, trail, floor,
         ATR gate, pyramid, session filter, weekend-flat) over 2021-11-12..2026-11-07
Stage 2  refine the stage-1 leader (risk, USD-direction cap, floor, min stop)
Checks   walk-forward (pick on 2021-11..2024-12 only, test 2025-01..2026-11),
         parameter-neighbour stability, cost stress, crypto-Shahin baseline.

Output: forex/reports/shahin_fx_5y.json (+ trades/equity of the winner)
"""
from __future__ import annotations

import itertools
import json
import os
import sys
import time
from dataclasses import asdict, replace
from multiprocessing import Pool
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from shahin_fx import Config, Costs, PAIRS, crypto_shahin_as_is, key, prepare, run  # noqa: E402

HERE = Path(__file__).resolve().parent
START, END = "2021-11-12", "2026-11-07"           # last data minute: Fri 2026-11-06 21:58 UTC
IS_END = "2025-01-01"                              # walk-forward split
MIN_TRADES = 40

PR = None


def init():
    global PR
    PR = prepare(HERE / "data")


def job(args):
    cfg, start, end, costs = args
    r = run(PR, cfg, costs, start, end)
    r["cfg"] = asdict(cfg)
    return r


def grid():
    out = []
    for tf, preset, n, atr, trail, floor, gate, pyr, sess, wk in itertools.product(
            ("1h", "4h", "D1"), ("standard", "crypto", "none"), (10, 20, 55, 100), (1.5, 2.0, 3.0),
            ("DON10", "DON20", "DON10_KIJUN", "CHAND3"), (True, False), (True, False), (True, False),
            (False, True), (False, True)):
        if tf == "D1" and sess:
            continue  # D1 bars close at 22:00 UTC, outside any session window
        out.append(Config(tf=tf, preset=preset, donchian=n, atr_mult=atr, trail=trail, profit_floor=floor,
                          atr_gate=gate, pyramid=pyr, session=sess, weekend_flat=wk,
                          min_stop_pips=10.0))
    return out


def rank_value(r):
    if r["trades"] < MIN_TRADES or r["cagr_pct"] <= 0:
        return -1e9 + r["cagr_pct"]
    return r["calmar"]


def pmap(pool, cfgs, start, end, costs, chunks=8):
    return pool.map(job, [(c, start, end, costs) for c in cfgs], chunksize=chunks)


def neighbours(c: Config):
    alts = {"donchian": (10, 20, 55, 100), "atr_mult": (1.5, 2.0, 3.0),
            "preset": ("standard", "crypto", "none"), "trail": ("DON10", "DON20", "DON10_KIJUN", "CHAND3")}
    out = []
    for field, vals in alts.items():
        cur = getattr(c, field)
        i = vals.index(cur)
        for j in (i - 1, i + 1):
            if 0 <= j < len(vals):
                out.append(replace(c, **{field: vals[j]}))
    for field in ("profit_floor", "atr_gate", "pyramid", "weekend_flat"):
        out.append(replace(c, **{field: not getattr(c, field)}))
    return out


def slim(r):
    return {k: r[k] for k in ("config", "cagr_pct", "max_dd_pct", "calmar", "sharpe", "trades", "win_rate_pct",
                              "profit_factor", "return_pct", "final_equity", "yearly_pct", "per_pair_net_usd",
                              "swap_usd", "exposure_pct")}


def main():
    t0 = time.time()
    costs = Costs()
    out_dir = HERE / "reports"
    out_dir.mkdir(exist_ok=True)
    with Pool(os.cpu_count(), initializer=init) as pool:
        cfgs = grid()
        print(f"stage 1: {len(cfgs)} configs", flush=True)
        full = pmap(pool, cfgs, START, END, costs)
        print(f"  done {time.time() - t0:.0f}s", flush=True)
        full.sort(key=rank_value, reverse=True)
        leader = Config(**full[0]["cfg"])

        # stage 2: refine leader (and the next 4 distinct leaders) on risk/portfolio knobs
        refine = []
        for r in full[:5]:
            base = Config(**r["cfg"])
            for risk, ucap, ft, fl, ms in itertools.product((0.005, 0.01, 0.015, 0.02), (1, 2, 3),
                                                            (1.0, 1.5, 2.0), (0.1, 0.5), (10.0, 20.0)):
                refine.append(replace(base, risk=risk, usd_cap=ucap, floor_trigger_r=ft, floor_lock_r=fl,
                                      min_stop_pips=ms))
        refine = list({key(c) + f"|{c.floor_trigger_r}|{c.floor_lock_r}": c for c in refine}.values())
        print(f"stage 2: {len(refine)} configs", flush=True)
        ref = pmap(pool, refine, START, END, costs)
        # risk is a leverage choice, not an edge: pick on Calmar at the leader's risk
        # ladder, then report the risk ladder separately
        ref.sort(key=rank_value, reverse=True)
        winner_cfg = Config(**ref[0]["cfg"]) if rank_value(ref[0]) > rank_value(full[0]) else leader
        winner_cfg_1pct = replace(winner_cfg, risk=0.01)

        # walk-forward: choose on in-sample only with the same rule, test after
        is_res = pmap(pool, cfgs, START, IS_END, costs)
        is_res.sort(key=rank_value, reverse=True)
        wf_pick = [Config(**r["cfg"]) for r in is_res[:10]]
        wf_oos = pmap(pool, wf_pick, IS_END, END, costs, chunks=1)
        win_is = pmap(pool, [winner_cfg], START, IS_END, costs, chunks=1)[0]
        win_oos = pmap(pool, [winner_cfg], IS_END, END, costs, chunks=1)[0]

        nb = pmap(pool, neighbours(winner_cfg), START, END, costs, chunks=1)
        stress = {}
        for name, cst in {
            "base": costs,
            "spread_x1.5_slip0.5": replace(costs, spread_pips=tuple(1.5 * s for s in costs.spread_pips),
                                           slippage_pips=0.5),
            "spread_x2_slip1_comm10": replace(costs, spread_pips=tuple(2 * s for s in costs.spread_pips),
                                              slippage_pips=1.0, commission_rt_per_100k=10.0),
            "no_swap_markup": replace(costs, swap_markup_pct=0.0),
            "zero_cost": Costs(spread_pips=(0, 0, 0), slippage_pips=0, commission_rt_per_100k=0,
                               swap_markup_pct=0),
        }.items():
            stress[name] = slim(pool.apply(job, ((winner_cfg, START, END, cst),)))
        risk_ladder = pmap(pool, [replace(winner_cfg, risk=r) for r in (0.005, 0.0075, 0.01, 0.015, 0.02, 0.03)],
                           START, END, costs, chunks=1)
        per_pair = {}
        baseline = pool.apply(job, ((crypto_shahin_as_is(), START, END, costs),))
        naive = pool.apply(job, ((Config(tf="4h", min_stop_pips=10.0), START, END, costs),))

    init()
    detail = run(PR, winner_cfg, costs, START, END, detail=True)
    for p in PAIRS:
        per_pair[p] = {"net_usd": detail["per_pair_net_usd"][p], "trades": detail["per_pair_trades"][p]}

    by_tf = {}
    for r in full:
        tf = r["cfg"]["tf"]
        if tf not in by_tf:
            by_tf[tf] = slim(r)
    profitable = sum(1 for r in full if r["cagr_pct"] > 0)
    report = {
        "data": json.loads((HERE / "data" / "manifest_histdata.json").read_text()) | {"symbols": {
            p: {k: v for k, v in m.items() if k != "archives"}
            for p, m in json.loads((HERE / "data" / "manifest_histdata.json").read_text())["symbols"].items()}},
        "period": [START, END], "walk_forward_split": IS_END,
        "costs": asdict(costs),
        "selection_rule": f"max Calmar (CAGR / max mark-to-market DD) with >= {MIN_TRADES} trades and CAGR > 0",
        "stage1_count": len(cfgs), "stage1_profitable": profitable, "stage2_count": len(refine),
        "winner": {"config": asdict(winner_cfg), "key": key(winner_cfg), "full_5y": slim(detail),
                   "in_sample_2021_2024": slim(win_is), "out_of_sample_2025_2026": slim(win_oos)},
        "winner_at_1pct_risk": slim(pool_free_run(winner_cfg_1pct, costs)),
        "best_per_timeframe": by_tf,
        "stage1_top20": [slim(r) for r in full[:20]],
        "stage2_top10": [slim(r) | {"floor": [r["cfg"]["floor_trigger_r"], r["cfg"]["floor_lock_r"]]} for r in ref[:10]],
        "walk_forward": {"picked_in_sample_top10": [
            {"config": is_res[i]["config"], "in_sample": slim(is_res[i]), "out_of_sample": slim(wf_oos[i])}
            for i in range(len(wf_pick))]},
        "neighbour_stability": [slim(r) for r in nb],
        "cost_stress": stress,
        "risk_ladder": [slim(r) for r in risk_ladder],
        "crypto_shahin_as_is": slim(baseline),
        "naive_4h_port_10pip_min_stop": slim(naive),
        "runtime_s": round(time.time() - t0, 1),
    }
    (out_dir / "shahin_fx_5y.json").write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n")
    (out_dir / "shahin_fx_5y_winner_trades.json").write_text(json.dumps(
        {"config": key(winner_cfg), "trades": detail["trade_list"], "equity_curve": detail["equity_curve"]},
        indent=0) + "\n")
    (out_dir / "stage1_top300.json").write_text(json.dumps([slim(r) for r in full[:300]], indent=0) + "\n")
    print(json.dumps(report["winner"], indent=1))
    print(f"total {time.time() - t0:.0f}s")


def pool_free_run(cfg, costs):
    if PR is None:
        init()
    return run(PR, cfg, costs, START, END)


if __name__ == "__main__":
    main()
