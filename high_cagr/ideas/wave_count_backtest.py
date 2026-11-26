"""Offline mechanical wave counts and shared-margin replay of archived bot legs."""

import hashlib
import json
import pickle
import pickletools
from pathlib import Path
import zipfile

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "high_cagr/output/ideas/wave_count"
START, SPLIT, END = pd.to_datetime(["2021-10-05", "2025-01-01", "2026-10-05"])
DATES = pd.date_range(START, END, inclusive="left")
MINUTES = len(DATES) * 1440
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT")
METHODS = ("wave2", "abc")
BOTS = ("main", "c3", "pa")
RISK = dict(main=.01, c3=.004, pa=.004, wave2=.004, abc=.004)
SEED, LEVERAGE, CAP = 10_000., 5, .8
FEE, SLIP, BAR = .0006, .0002, 240


def read_market(symbol, manifest):
    cache = ROOT / ("btc_backtest/cache" if symbol == "BTCUSDT" else "portfolio/cache")
    ohlc, rates = [], []
    for record in manifest:
        if record["symbol"] != symbol:
            continue
        path = cache / record["name"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != record["sha256"]:
            raise ValueError(f"Checksum mismatch: {path}")
        with zipfile.ZipFile(path) as z, z.open(z.namelist()[0]) as source:
            if "-1m-" in path.name:
                raw = pd.read_csv(source, header=None, usecols=range(5), dtype=str)
                ohlc.append(raw[pd.to_numeric(raw[0], errors="coerce").notna()].astype(float))
            elif "-fundingRate-" in path.name:
                rates.append(pd.read_csv(source, usecols=["calc_time", "last_funding_rate"]))
    frame = pd.concat(ohlc, ignore_index=True)
    ts = frame.pop(0).to_numpy(dtype=np.int64)
    ts = np.where(ts > 10**14, ts // 1000, ts)
    start = START.value // 10**6
    frame.index = ts
    frame = frame.loc[(frame.index >= start) & (frame.index < start + MINUTES * 60000)]
    frame = frame.sort_index()
    if not np.array_equal(frame.index.to_numpy(), start + np.arange(MINUTES) * 60000):
        raise ValueError(f"Missing or duplicate minutes: {symbol}")
    price = frame.to_numpy()
    assert np.isfinite(price).all() and (price > 0).all()
    funding = np.zeros(MINUTES)
    rate = pd.concat(rates, ignore_index=True)
    minute = (rate.calc_time.to_numpy(dtype=np.int64) - start) // 60000
    keep = (minute >= 0) & (minute < MINUTES)
    assert not pd.Index(minute[keep]).has_duplicates
    funding[minute[keep]] = rate.last_funding_rate.to_numpy()[keep]
    return price, np.r_[0., np.cumsum(funding)]


def pattern(pivots, method):
    side = pivots[-1][0] * -1
    count = 3 if method == "wave2" else 9
    if len(pivots) < count:
        return None
    prices = [side * price for _, price in pivots[-count:]]
    p0, p1, p2 = prices[:3]
    if not p0 < p2 < p1:
        return None
    if method == "wave2":
        if .382 <= (p1 - p2) / (p1 - p0) <= .786:
            return side, side * p1, side * p2
        return None
    p3, p4, p5, a, b, c = prices[3:]
    if (p1 < p4 < p3 < p5 and p3 - p2 >= min(p1 - p0, p5 - p4)
            and p0 < c < a < b < p5 and .382 <= (p5 - c) / (p5 - p0) <= .786):
        return side, side * b, side * c
    return None


def signals(high, low, close):
    true_range = np.maximum(high - low, np.maximum(
        np.abs(high - np.r_[close[0], close[:-1]]), np.abs(low - np.r_[close[0], close[:-1]])))
    atr = pd.Series(true_range).ewm(alpha=1/14, adjust=False, min_periods=14).mean().to_numpy()
    result = {method: {} for method in METHODS}
    pending = {}
    pivots = []
    extreme = close[0]
    direction = 0
    for t, current in enumerate(close):
        if not np.isfinite(atr[t]):
            continue
        threshold = 1.5 * atr[t]
        if not direction:
            if abs(current - extreme) >= threshold:
                direction = 1 if current > extreme else -1
                pivots.append((-direction, extreme))
                extreme = current
        elif direction * (current - extreme) >= 0:
            extreme = current
        elif direction * (extreme - current) >= threshold:
            pivots.append((direction, extreme))
            direction = -direction
            extreme = current
            pending = {method: (t, pattern(pivots, method)) for method in METHODS}
        for method, (confirmed, setup) in list(pending.items()):
            if setup is None or t - confirmed > 12:
                del pending[method]
                continue
            side, trigger, pivot = setup
            if side * (current - pivot) <= 0:
                del pending[method]
            elif side * (current - trigger) > 0:
                result[method][t] = (side, pivot - side * .1 * atr[t])
                del pending[method]
    return result


def wave_legs(symbol, price, funding):
    bars = price.reshape(-1, BAR, 4)
    high, low, close = bars[:, :, 1].max(1), bars[:, :, 2].min(1), bars[:, -1, 3]
    full = signals(high, low, close)
    for n in (len(close) // 3, len(close) * 2 // 3):
        truncated = signals(high[:n], low[:n], close[:n])
        for method in METHODS:
            assert truncated[method] == {t: x for t, x in full[method].items() if t < n}
    for method, orders in full.items():
        last_exit = -1
        for t, (side, stop) in orders.items():
            em = (t + 1) * BAR
            if em <= last_exit or em >= len(price):
                continue
            raw_entry = price[em, 0]
            entry = raw_entry * (1 + side * SLIP)
            distance = side * (entry - stop)
            if side * (raw_entry - stop) <= 0 or distance / entry < .002:
                continue
            target = entry + side * 2 * distance
            end = min(em + 18 * BAR, len(price))
            hi, lo = price[em:end, 1], price[em:end, 2]
            stopped, took = (lo <= stop, hi >= target) if side == 1 else (hi >= stop, lo <= target)
            hits = np.flatnonzero(stopped | took)
            if len(hits):
                hit = hits[0]
                xm = em + hit
                level = stop if stopped[hit] else target
                op = price[xm, 0]
                exit_raw = (min if stopped[hit] == (side == 1) else max)(op, level)
            else:
                xm = end - 1
                exit_raw = price[xm, 3]
            exit_price = exit_raw * (1 - side * SLIP)
            unit = (side * (exit_price - entry) - FEE * (exit_price + entry)
                    - side * raw_entry * (funding[xm + 1] - funding[em + 1]))
            yield dict(bot=method, coin=symbol, side=side, em=em, xm=xm, entry=entry, unit=unit,
                       stop_frac=distance / entry, risk_scale=1., root=(method, symbol, em), is_add=False)
            last_exit = xm


def load_bots():
    path = ROOT / "high_cagr/output/ideas/winrate/raw_legs.pkl"
    blob = path.read_bytes()
    # Permit only primitive container/data opcodes from the repository's frozen ledger.
    safe = set(("PROTO FRAME EMPTY_LIST MEMOIZE MARK EMPTY_DICT SHORT_BINUNICODE BINGET "
                "LONG_BINGET BININT BININT1 BININT2 BINFLOAT TUPLE2 TUPLE3 NEWFALSE NEWTRUE "
                "SETITEMS APPENDS STOP").split())
    if any(op.name not in safe for op, _, _ in pickletools.genops(blob)):
        raise ValueError("Unexpected opcode in bot ledger")
    return pickle.loads(blob)


def replay(legs, bots):
    active = [leg for leg in legs if leg["bot"] in bots]
    events = []
    for i, leg in enumerate(active):
        assert 0 <= leg["em"] <= leg["xm"] < MINUTES
        assert leg["entry"] > 0 and leg["stop_frac"] > 0
        events.extend(((leg["em"], 0, i), (leg["xm"], 1, i)))
    events.sort()
    cash, margin = SEED, 0.
    opened, rejected_roots, closed = {}, set(), []
    pnl_by_day = np.zeros(len(DATES))
    rejected = dict.fromkeys(bots, 0)
    reduced = dict.fromkeys(bots, 0)
    for minute, event, i in events:
        leg = active[i]
        bot, root = leg["bot"], leg["root"]
        if event == 0:
            if leg["is_add"] and root in rejected_roots:
                rejected[bot] += 1
                continue
            wanted = cash * RISK[bot] * leg["risk_scale"] / (leg["stop_frac"] + 2 * (FEE + SLIP))
            available = max(0., CAP * cash - margin) * LEVERAGE / (1 + CAP * LEVERAGE * 2 * FEE)
            notional = min(wanted, available)
            if notional < 20:
                if not leg["is_add"]:
                    rejected_roots.add(root)
                rejected[bot] += 1
                continue
            reduced[bot] += int(notional < wanted)
            opened[i] = notional
            margin += notional / LEVERAGE
        elif i in opened:
            notional = opened.pop(i)
            margin -= notional / LEVERAGE
            pnl = notional * leg["unit"] / leg["entry"]
            cash += pnl
            pnl_by_day[minute // 1440] += pnl
            closed.append((bot, leg["coin"], leg["side"], leg["em"], minute, notional, pnl))
    assert not opened and abs(margin) < 1e-5
    curve = SEED + pnl_by_day.cumsum()
    assert np.isclose(cash, curve[-1])
    return curve, closed, rejected, reduced


def metrics(curve, trades, first, last):
    start = curve[first - 1] if first else SEED
    path = np.r_[start, curve[first:last]]
    values = np.array([r[-1] for r in trades if first <= r[4] // 1440 < last])
    gains, losses = values[values > 0].sum(), -values[values < 0].sum()
    return dict(return_pct=100 * (path[-1] / start - 1),
                cagr_pct=100 * ((path[-1] / start)**(365.25 / (last - first)) - 1),
                max_drawdown_pct=100 * np.max(1 - path / np.maximum.accumulate(path)),
                closed_legs=len(values), win_pct=100 * float((values > 0).mean()) if len(values) else None,
                profit_factor=float(gains / losses) if losses else None, end_equity=float(path[-1]))


def main():
    inputs = ROOT / "portfolio/output"
    manifest = sum((json.loads((inputs / name).read_text())
                    for name in ("data_manifest.json", "repair_manifest.json")), [])
    legs = load_bots()
    source_bot_counts = {bot: sum(leg["bot"] == bot for leg in legs) for bot in BOTS}
    for coin in SYMBOLS:
        price, funding = read_market(coin, manifest)
        legs.extend(wave_legs(coin, price, funding))
        print("Verified and simulated", coin, flush=True)
    scenarios = {"+".join(bots): bots for bots in [
        *((bot,) for bot in (*BOTS, *METHODS)), BOTS,
        *((bot, method) for bot in BOTS for method in METHODS),
        *(BOTS + (method,) for method in METHODS),
    ]}
    split = DATES.get_loc(SPLIT)
    curves, trade_frames, results = {}, [], {}
    for name, bots in scenarios.items():
        curve, trades, rejected, reduced = replay(legs, bots)
        curves[name] = curve
        trade_frames.append(pd.DataFrame(trades, columns=[
            "bot", "coin", "side", "entry_min", "exit_min", "notional", "pnl"]).assign(scenario=name))
        results[name] = dict(full=metrics(curve, trades, 0, len(DATES)),
                             train=metrics(curve, trades, 0, split),
                             validation=metrics(curve, trades, split, len(DATES)),
                             rejected=rejected, margin_reduced=reduced,
                             closed_by_bot={b: sum(r[0] == b for r in trades) for b in bots})
    OUT.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(curves, index=DATES).to_csv(OUT / "daily_equity.csv", index_label="date_utc", float_format="%.8f")
    pd.concat(trade_frames, ignore_index=True).to_csv(OUT / "trades.csv", index=False, float_format="%.8f")
    (OUT / "summary.json").write_text(json.dumps(dict(
        symbols=SYMBOLS, start_utc=str(START.date()), end_utc=str(DATES[-1].date()),
        validation_from_utc=str(SPLIT.date()), risk=RISK, archived_bot_legs=source_bot_counts,
        scenarios=results), indent=2, allow_nan=False) + "\n")


if __name__ == "__main__":
    main()
