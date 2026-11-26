import argparse
from concurrent.futures import ProcessPoolExecutor
import hashlib
from itertools import combinations
import json
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from high_cagr.ideas.wave_count_backtest import load_bots
from .backtest_engine import execute
from .data_loader import ROOT, aggregate, load
from .entry_models import confirmations
from .metrics import score
from .optimizer import bot_subsets, candidates, choose_variants, development_rank, distinct_finalists
from .portfolio import pack_bots, pack_waves, replay
from .risk_manager import single_book
from .robustness import block_bootstrap
from .strategies import NAMES, NOT_TESTED, PROXIES, generate
from .wave_engine import atr, ema, lag

PACKAGE = Path(__file__).resolve().parent
RISKS = (.0025, .005, .01, .02)


def periods(cfg):
    days = pd.date_range(cfg["start"], cfg["end_exclusive"], inclusive="left")
    train, validation = len(days)*3//5, len(days)*4//5
    if train < 1 or train == validation:
        raise ValueError("At least five calendar days required")
    return days, (("train", 0, train), ("validation", train, validation), ("final", validation, len(days)))


def filter_signal(signal, bars, a, mins, mode):
    if mode == "none":
        return signal
    _, _, _, close, volume = bars.T
    if mode.startswith("ema"):
        good = signal * (close - ema(close, int(mode[3:]))) > 0
    elif mode == "rsi":
        change = close - lag(close, 1)
        good = signal * (ema(np.maximum(change, 0), 14) - ema(np.maximum(-change, 0), 14)) > 0
    elif mode == "macd":
        macd = ema(close, 12) - ema(close, 26)
        good = signal * (macd - ema(macd, 9)) > 0
    elif mode == "relative_volume":
        good = volume > 1.2 * pd.Series(volume).rolling(20).mean().shift().to_numpy()
    elif mode in ("high_atr", "low_atr"):
        pct = a / close
        median = pd.Series(pct).rolling(50).median().shift().to_numpy()
        good = pct > median if mode == "high_atr" else pct < median
    else:
        opening, closing = {"utc_asia": (0, 8), "utc_europe": (7, 16), "utc_america": (13, 22)}[mode]
        hour = ((np.arange(len(close))+1)*mins % 1440)//60
        good = (hour >= opening) & (hour < closing)
    return np.where(good, signal, 0).astype(np.int8)


def plan(cfg):
    return {**cfg["baseline"], "entry_mode": 13, "stop_mode": 6, "filter_mode": "none",
            "exit_mode": 0, "management_r": 0.}


def fill(prices, funding, bars, a, signal, mins, cfg, params, direction=0, stress=1.):
    f = cfg["friction"]
    return execute(prices, funding, bars, a, filter_signal(signal, bars, a, mins, params["filter_mode"]),
                   mins, params["entry_mode"], params["stop_mode"], params["target_r"], params["max_hold"],
                   stress*f["fee_per_side"], stress*f["slippage_per_fill"], params["min_stop"], direction,
                   confirmations(bars, params["entry_mode"]), params["exit_mode"], params["management_r"])


def evaluate(fills, prices, funding, cfg, risk, compound=True, stress=1., scope=None):
    days, splits = periods(cfg)
    f = cfg["friction"]
    curve, pnl, qty = single_book(fills, prices, funding, len(days), risk, f["leverage"],
                                 f["margin_cap"], stress*f["fee_per_side"], stress*f["slippage_per_fill"], compound)
    end_day = fills[:, 1] // 1440
    out = []
    for period, start, end in splits:
        if scope is not None and period not in scope:
            continue
        mask = (qty > 0) & (end_day >= start) & (end_day < end)
        metrics = score(curve, pnl[mask], fills[mask], start, end)
        exposure = np.maximum(0, np.minimum(fills[:, 1]+1, end*1440) - np.maximum(fills[:, 0], start*1440))
        metrics["exposure_pct"] = float(100 * exposure[qty > 0].sum()/((end-start)*1440))
        out.append(dict(period=period, **metrics, transaction_costs=float((qty[mask]*fills[mask, 7]).sum())))
    return out, curve, pnl, qty


def write(frame, path):
    tmp = path.with_name(path.name + ".tmp")
    compression = dict(method="gzip", mtime=0) if path.suffix == ".gz" else None
    frame.to_csv(tmp, index=False, compression=compression, float_format="%.9g")
    tmp.replace(path)


def robustness_runs(name, prices, funding, bars, a, signal, mins, cfg, params, train_end):
    prior = pd.Series(bars[:, 3]).pct_change(24).abs().shift().to_numpy()
    cutoff = np.nanmedian(prior[:train_end*1440//mins])
    regimes, stress = [], []
    for mode, mask in (("trend_proxy", prior >= cutoff), ("range_proxy", prior < cutoff)):
        selected = np.where(mask, signal, 0).astype(np.int8)
        run = fill(prices, funding, bars, a, selected, mins, cfg, params)
        stats, _, _, _ = evaluate(run, prices, funding, cfg, params["risk"])
        regimes.extend(dict(strategy=name, regime=mode, **x) for x in stats)
    for multiplier in (1., 1.5, 2., 3.):
        run = fill(prices, funding, bars, a, signal, mins, cfg, params, stress=multiplier)
        stats, _, _, _ = evaluate(run, prices, funding, cfg, params["risk"], stress=multiplier)
        stress.extend(dict(strategy=name, multiplier=multiplier, **x) for x in stats)
    return regimes, stress


def scan_job(job):
    symbol, cfg, checkpoint = job
    target = Path(checkpoint) / (symbol + ".csv")
    if target.exists():
        return str(target)
    prices, funding = load(symbol, cfg)
    params = plan(cfg)
    rows = []
    for label, mins in cfg["timeframes"].items():
        bars = aggregate(prices, mins)
        a = atr(bars, params["atr_period"])
        signals, pivots = generate(bars, a, params["atr_multiple"], params["fib_tolerance"])
        # Re-run detection with two different ends on every market/timeframe.
        for cutoff in (len(bars)//3, 2*len(bars)//3):
            partial, short_pivots = generate(bars[:cutoff], a[:cutoff], params["atr_multiple"], params["fib_tolerance"])
            assert np.array_equal(partial, signals[:, :cutoff])
            assert np.array_equal(short_pivots, pivots[pivots[:, 1] < cutoff])
        for strategy, signal in enumerate(signals, 1):
            if strategy in NOT_TESTED:
                continue
            for direction in (0, 1, -1):
                fills = fill(prices, funding, bars, a, signal, mins, cfg, params, direction)
                sizing = [(risk, compound) for risk in RISKS for compound in (False, True)] if direction == 0 else [(params["risk"], True)]
                for risk, compound in sizing:
                    stats, _, _, _ = evaluate(fills, prices, funding, cfg, risk, compound)
                    rows.extend(dict(strategy=strategy, symbol=symbol, timeframe=label,
                                     risk=risk, sizing="compound" if compound else "fixed",
                                     direction=direction, **x) for x in stats)
        print(f"Baseline {symbol} {label}", flush=True)
    write(pd.DataFrame(rows), target)
    return str(target)


def research(frame, cfg, out):
    rank = development_rank(frame, cfg)
    if rank.empty:
        raise RuntimeError("No baseline configuration met the training eligibility floor")
    optimize = set(rank.head(cfg["selection"]["optimize_strategies"]).strategy)
    plans, trials, ledgers, bounds, stress_rows, regimes, walk = {}, [], {}, [], [], [], []
    trade_history, curves = [], {}
    days, splits = periods(cfg)
    for symbol, group in rank.groupby("symbol"):
        prices, funding = load(symbol, cfg)
        for label, cases in group.groupby("timeframe"):
            mins = cfg["timeframes"][label]
            bars = aggregate(prices, mins)
            for obj in cases.itertuples():
                strategy = int(obj.strategy)
                variants = list(candidates(plan(cfg), cfg["seed"]+strategy)) if strategy in optimize else [plan(cfg)]
                cached, atrs, study, trial_curves = {}, {}, [], []
                for trial, params in enumerate(variants):
                    signature = (params["atr_period"], params["atr_multiple"], params["fib_tolerance"])
                    # Cache one signal row per wave setting, never the full matrix.
                    if signature not in cached:
                        if signature[0] not in atrs:
                            atrs[signature[0]] = atr(bars, signature[0])
                        a = atrs[signature[0]]
                        signals, _ = generate(bars, a, *signature[1:])
                        cached[signature] = (a, signals[strategy-1].copy())
                        del signals
                    a, signal = cached[signature]
                    fills = fill(prices, funding, bars, a, signal, mins, cfg, params)
                    stats, candidate_curve, _, _ = evaluate(fills, prices, funding, cfg, params["risk"],
                                                               scope=("train", "validation"))
                    trial_curves.append(candidate_curve[:splits[1][2]])
                    study.extend(dict(strategy=strategy, trial=trial, **params, **item) for item in stats)
                idx = choose_variants(pd.DataFrame(study))
                trials.extend(study)
                params = variants[idx]
                a = atr(bars, params["atr_period"])
                signals, _ = generate(bars, a, params["atr_multiple"], params["fib_tolerance"])
                signal = signals[strategy-1].copy()
                del signals
                fills = fill(prices, funding, bars, a, signal, mins, cfg, params)
                stats, curve, pnl, qty = evaluate(fills, prices, funding, cfg, params["risk"])
                val = stats[1]
                name = f"S{strategy:02d}"
                if strategy in optimize:
                    for percent in (60, 70):
                        first, last = len(days)*percent//100, len(days)*(percent+10)//100
                        empty = np.empty((0, 2))
                        eligible_trials = {s["trial"] for s in study if s["period"] == "train" and s["trades"] >= 20}
                        trains = [score(c, np.empty(0), empty, 0, first) for c in trial_curves]
                        chosen = max(eligible_trials or {0}, key=lambda j: (
                            trains[j]["sharpe"]-.015*trains[j]["drawdown_pct"], -j))
                        summary = score(trial_curves[chosen], np.empty(0), empty, first, last)
                        walk.append(dict(strategy=name, trial=chosen, train_through=days[first-1].date(),
                                         forward_from=days[first].date(), forward_through=days[last-1].date(),
                                         **{metric:summary[metric] for metric in
                                            ("return_pct", "drawdown_pct", "sharpe")}))
                plans[name] = dict(strategy=strategy, name=NAMES[strategy-1], symbol=symbol, timeframe=label,
                                   trial=idx, params=params, periods=stats,
                                   rank_score=val["sharpe"]-.015*val["drawdown_pct"])
                ledgers[name] = pack_waves(fills, params["risk"])
                if strategy in optimize:
                    t = pd.DataFrame(fills, columns=["entry_min", "exit_min", "side", "entry", "exit",
                                                   "stop_distance", "unit_pnl", "unit_cost", "mae_r", "mfe_r", "stop", "target"])
                    trade_history.append(t.assign(strategy=name, symbol=symbol, timeframe=label, quantity=qty, pnl=pnl))
                    curves[name] = curve
                    r, s = robustness_runs(name, prices, funding, bars, a, signal, mins, cfg, params, splits[0][2])
                    regimes.extend(r)
                    stress_rows.extend(s)
    # Validation selects the finalists. Their final-period scores are report-only.
    finalists = distinct_finalists(plans, cfg["selection"]["finalists"])
    mc = []
    for name in finalists:
        if name not in curves:
            # Existing plans outside optimization can be finalists; rerun only that market.
            p = plans[name]
            prices, funding = load(p["symbol"], cfg)
            mins = cfg["timeframes"][p["timeframe"]]
            bars = aggregate(prices, mins)
            params = p["params"]
            a = atr(bars, params["atr_period"])
            signals, _ = generate(bars, a, params["atr_multiple"], params["fib_tolerance"])
            signal = signals[p["strategy"]-1]
            fills = fill(prices, funding, bars, a, signal, mins, cfg, params)
            _, curves[name], pnl, qty = evaluate(fills, prices, funding, cfg, params["risk"])
            t = pd.DataFrame(fills, columns=["entry_min", "exit_min", "side", "entry", "exit",
                                           "stop_distance", "unit_pnl", "unit_cost", "mae_r", "mfe_r", "stop", "target"])
            trade_history.append(t.assign(strategy=name, symbol=p["symbol"], timeframe=p["timeframe"],
                                          quantity=qty, pnl=pnl))
            r, s = robustness_runs(name, prices, funding, bars, a, signal, mins, cfg, params, splits[0][2])
            regimes.extend(r)
            stress_rows.extend(s)
        first = splits[-1][1]
        curve = curves[name]
        returns = np.diff(curve[first-1:]) / curve[first-1:-1]
        sims = block_bootstrap(returns, cfg["bootstrap"]["replications"], cfg["bootstrap"]["block_days"], cfg["seed"])
        mc.append(pd.DataFrame(sims, columns=["return_pct", "dd_pct"]).assign(strategy=name))
        bounds.append(dict(strategy=name, return_p025=float(np.quantile(sims[:, 0], .025)),
                           return_p975=float(np.quantile(sims[:, 0], .975)),
                           loss_probability=float(np.mean(sims[:, 0] < 0)),
                           dd_p95=float(np.quantile(sims[:, 1], .95))))
    write(pd.DataFrame(trials), out/"optimization_trials.csv.gz")
    write(pd.DataFrame(stress_rows), out/"cost_stress.csv")
    write(pd.DataFrame(regimes), out/"regimes.csv")
    write(pd.DataFrame(walk), out/"walk_forward.csv")
    write(pd.concat(trade_history, ignore_index=True), out/"trade_history.csv.gz")
    write(pd.concat(mc, ignore_index=True), out/"monte_carlo_results.csv.gz")
    write(pd.DataFrame(bounds), out/"bootstrap_intervals.csv")
    equity = pd.DataFrame(curves, index=days)
    write(equity.rename_axis("date").reset_index(), out/"equity.csv")
    for frequency, filename in (("ME", "monthly_returns.csv"), ("YE", "yearly_returns.csv")):
        sampled = equity.resample(frequency).last()
        returns = (sampled/sampled.shift().fillna(10000.)-1)*100
        write(returns.rename_axis("period_end").reset_index(), out/filename)
    (out/"best_parameters.json").write_text(json.dumps(dict(finalists=finalists, plans=plans), indent=2, allow_nan=False)+"\n")
    return plans, ledgers, finalists


def portfolios(plans, ledgers, finalists, cfg):
    if cfg["start"] != "2021-10-05" or cfg["end_exclusive"] != "2026-10-05":
        raise ValueError("The archived bot ledger requires the original five-year bounds")
    bots = pack_bots(load_bots())
    days, splits = periods(cfg)
    cases = [((), b) for b in bot_subsets()]
    cases.extend(((name,), subset) for name in ledgers for subset in [(), *bot_subsets()])
    cases.extend((pair, subset) for pair in combinations(ledgers, 2) for subset in [(), *bot_subsets()])
    for size in range(3, len(finalists)+1):
        cases.extend((combo, subset) for combo in combinations(sorted(finalists), size) for subset in [(), *bot_subsets()])
    rows = []
    for ws, bs in dict.fromkeys((tuple(sorted(w)), b) for w, b in cases):
        curve, pnl, fills = replay([*(bots[b] for b in bs), *(ledgers[w] for w in ws)], len(days), cfg)
        exits = fills[:, 1]//1440
        for period, start, end in splits:
            mask = (exits >= start) & (exits < end)
            metrics = score(curve, pnl[mask], fills[mask], start, end)
            metrics.pop("exposure_pct")  # Portfolio leg durations can overlap.
            rows.append(dict(waves="+".join(ws), bots="+".join(bs), period=period, **metrics))
    return pd.DataFrame(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=PACKAGE/"config.yaml")
    parser.add_argument("--output", type=Path, default=PACKAGE/"results")
    parser.add_argument("--checkpoint", type=Path, default=ROOT/".wave-research-cache")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--baseline-only", action="store_true")
    args = parser.parse_args()
    cfg = yaml.safe_load(args.config.read_text())
    signature = hashlib.sha256(args.config.read_bytes())
    for path in sorted(PACKAGE.rglob("*.py")):
        signature.update(path.read_bytes())
    for name in ("data_manifest.json", "repair_manifest.json"):
        signature.update((ROOT/cfg["manifest_directory"]/name).read_bytes())
    checkpoint = args.checkpoint/signature.hexdigest()[:20]
    checkpoint.mkdir(parents=True, exist_ok=True)
    args.output.mkdir(parents=True, exist_ok=True)
    jobs = [(s, cfg, str(checkpoint)) for s in cfg["symbols"]]
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        baseline = pd.concat((pd.read_csv(x) for x in pool.map(scan_job, jobs)), ignore_index=True)
    write(baseline, args.output/"all_results.csv.gz")
    (args.output/"run_config.json").write_text(json.dumps(dict(
        fingerprint=signature.hexdigest(), config=cfg, baseline_trials=len(baseline)//3,
        split=[(p, str(periods(cfg)[0][a].date()), str(periods(cfg)[0][b-1].date()))
               for p, a, b in periods(cfg)[1]]), indent=2)+"\n")
    if not args.baseline_only:
        plans, ledgers, finalists = research(baseline, cfg, args.output)
        print(f"Selected {len(plans)} strategies for portfolio replay; finalists: {finalists}", flush=True)
        write(portfolios(plans, ledgers, finalists, cfg), args.output/"portfolio_results.csv.gz")
        from .report import render
        render(args.output, plans, finalists, baseline, cfg)


if __name__ == "__main__":
    main()
