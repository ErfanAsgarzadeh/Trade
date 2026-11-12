#!/usr/bin/env python3
"""Shahin-FX: the Shahin breakout core re-engineered for spot forex.

What stays from crypto Shahin
    * closed-bar Donchian breakout confirmed outside the shifted Ichimoku Kumo
    * ATR initial stop, Donchian stop-trail, optional Kijun close-exit (hybrid)
    * profit floor (move stop to +lock R after +trigger R), ATR regime gate
    * optional one-step pyramid at +2R with half risk and the shared stop
    * 2% rolling-24h realised loss brake, risk-% position sizing

What is different for forex (all switchable / optimisable)
    * bars aligned to the FX session (22:00 UTC = 17:00 New York), so there is
      no fake Sunday stub candle; 1h / 4h / D1 timeframes
    * minimum stop in **pips** instead of crypto's 1.2 % (which would reject
      almost every FX trade)
    * bid/ask execution: buy at ask, sell at bid, spread per pair, commission
      per 100k USD notional, slippage in pips
    * overnight swap from approximate central-bank policy-rate differentials
      plus broker markup, Wednesday triple roll
    * session filter (enter only in London/New-York hours)
    * optional flat-before-weekend (avoid Sunday gap risk)
    * USD-direction cap: EURUSD long, GBPUSD long and USDJPY short are all
      "short USD" -> limit how many same-direction USD bets are open
    * gross leverage cap (retail majors 30:1; default 20:1)
    * USDJPY P&L converted from JPY to USD at the current rate

One shared USD account trades all three pairs at once (portfolio result).
Minute bars drive fills, stops, marks, swaps and drawdown.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, asdict, field
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from numba import njit

PAIRS = ("EURUSD", "GBPUSD", "USDJPY")
PIP = {"EURUSD": 1e-4, "GBPUSD": 1e-4, "USDJPY": 1e-2}
MINUTE_MS, HOUR_MS, DAY_MS = 60_000, 3_600_000, 86_400_000
SESSION_OFFSET_MS = 22 * HOUR_MS  # FX day starts 17:00 New York = 22:00 UTC
TF_MS = {"15m": 15 * MINUTE_MS, "30m": 30 * MINUTE_MS, "1h": HOUR_MS, "2h": 2 * HOUR_MS, "4h": 4 * HOUR_MS,
         "8h": 8 * HOUR_MS, "12h": 12 * HOUR_MS, "D1": DAY_MS, "W1": 7 * DAY_MS}
MIN_MINUTES = {"15m": 5, "30m": 10, "1h": 20, "2h": 40, "4h": 60, "8h": 120, "12h": 180, "D1": 300, "W1": 1500}
ICHIMOKU = {"standard": (9, 26, 52, 26), "crypto": (20, 60, 120, 30), "none": None}
SEED = 10_000.0

# Approximate central-bank policy rates (% p.a.), step changes by effective date.
# Used only to estimate overnight swap. Values after late-2025 are held flat.
POLICY_RATES = {
    "USD": [("2021-01-01", 0.125), ("2022-03-17", 0.375), ("2022-05-05", 0.875), ("2022-06-16", 1.625),
            ("2022-07-28", 2.375), ("2022-09-22", 3.125), ("2022-11-03", 3.875), ("2022-12-15", 4.375),
            ("2023-02-02", 4.625), ("2023-03-23", 4.875), ("2023-05-04", 5.125), ("2023-07-27", 5.375),
            ("2024-09-19", 4.875), ("2024-11-08", 4.625), ("2024-12-19", 4.375), ("2025-09-18", 4.125),
            ("2025-10-30", 3.875), ("2025-12-11", 3.625)],
    "EUR": [("2021-01-01", -0.50), ("2022-07-27", 0.00), ("2022-09-14", 0.75), ("2022-11-02", 1.50),
            ("2022-12-21", 2.00), ("2023-02-08", 2.50), ("2023-03-22", 3.00), ("2023-05-10", 3.25),
            ("2023-06-21", 3.50), ("2023-08-02", 3.75), ("2023-09-20", 4.00), ("2024-06-12", 3.75),
            ("2024-09-18", 3.50), ("2024-10-23", 3.25), ("2024-12-18", 3.00), ("2025-02-05", 2.75),
            ("2025-03-12", 2.50), ("2025-04-23", 2.25), ("2025-06-11", 2.00)],
    "GBP": [("2021-01-01", 0.10), ("2021-12-16", 0.25), ("2022-02-03", 0.50), ("2022-03-17", 0.75),
            ("2022-05-05", 1.00), ("2022-06-16", 1.25), ("2022-08-04", 1.75), ("2022-09-22", 2.25),
            ("2022-11-03", 3.00), ("2022-12-15", 3.50), ("2023-02-02", 4.00), ("2023-03-23", 4.25),
            ("2023-05-11", 4.50), ("2023-06-22", 5.00), ("2023-08-03", 5.25), ("2024-08-01", 5.00),
            ("2024-11-07", 4.75), ("2025-02-06", 4.50), ("2025-05-08", 4.25), ("2025-08-07", 4.00),
            ("2025-11-06", 4.00), ("2025-12-18", 3.75)],
    "JPY": [("2021-01-01", -0.10), ("2024-03-19", 0.05), ("2024-07-31", 0.25), ("2025-01-24", 0.50),
            ("2025-12-19", 0.75)],
}


@dataclass(frozen=True)
class Costs:
    spread_pips: tuple = (0.6, 0.9, 0.8)        # EURUSD, GBPUSD, USDJPY average all-in raw spread
    slippage_pips: float = 0.2                   # per market/stop fill
    commission_rt_per_100k: float = 7.0          # USD, round trip
    swap_markup_pct: float = 0.5                 # broker markup on each side, % p.a.
    leverage_cap: float = 20.0                   # gross notional / equity


@dataclass(frozen=True)
class Config:
    tf: str = "4h"
    preset: str = "standard"
    donchian: int = 10
    atr_mult: float = 2.0
    trail: str = "DON10_KIJUN"        # DON10 | DON20 | DON10_KIJUN | CHAND3
    profit_floor: bool = True
    floor_trigger_r: float = 1.0
    floor_lock_r: float = 0.1
    atr_gate: bool = True
    pyramid: bool = True
    session: bool = False            # enter only 07:00-20:00 UTC
    weekend_flat: bool = False
    usd_cap: int = 3                 # max open positions with the same USD direction
    min_stop_pips: float = 10.0
    risk: float = 0.01
    daily_loss: float = 0.02


def crypto_shahin_as_is() -> Config:
    """Crypto Shahin settings applied literally (incl. 1.2 % minimum stop)."""
    return Config(tf="4h", preset="standard", donchian=10, atr_mult=2.0, trail="DON10_KIJUN",
                  atr_gate=True, pyramid=True, session=False, weekend_flat=False, usd_cap=3,
                  min_stop_pips=-1.2, risk=0.01)  # negative = percent of price


def key(c: Config) -> str:
    return (f"{c.tf}|{c.preset}|N{c.donchian}|ATR{c.atr_mult:g}|{c.trail}|F{int(c.profit_floor)}"
            f"|G{int(c.atr_gate)}|P{int(c.pyramid)}|S{int(c.session)}|W{int(c.weekend_flat)}"
            f"|U{c.usd_cap}|MS{c.min_stop_pips:g}|R{c.risk:g}")


# ----------------------------------------------------------------- data
def load_minutes(data_dir: Path):
    frames = {}
    for pair in PAIRS:
        path = data_dir / "ohlcv" / f"{pair[:3]}_{pair[3:]}_bid_1m.csv"
        f = pd.read_csv(path, dtype={"timestamp": "int64"})
        frames[pair] = f
    times = np.unique(np.concatenate([f.timestamp.to_numpy() for f in frames.values()]))
    P, n = len(PAIRS), len(times)
    ohlc = np.full((4, P, n), np.nan)
    for p, pair in enumerate(PAIRS):
        f = frames[pair]
        idx = np.searchsorted(times, f.timestamp.to_numpy())
        for k, col in enumerate(("open", "high", "low", "close")):
            ohlc[k, p, idx] = f[col].to_numpy()
    return times, ohlc, frames


def make_bars(frame: pd.DataFrame, tf: str) -> pd.DataFrame:
    span = TF_MS[tf]
    # weekly bars open Sunday 22:00 UTC (1970-01-01 was a Thursday -> +3 days)
    offset = SESSION_OFFSET_MS + (3 * DAY_MS if tf == "W1" else 0)
    t = frame.timestamp.to_numpy()
    bucket = (t - offset) // span
    g = frame.assign(bucket=bucket).groupby("bucket", sort=True).agg(
        open=("open", "first"), high=("high", "max"), low=("low", "min"),
        close=("close", "last"), n=("close", "size"))
    g = g[g.n >= MIN_MINUTES[tf]].copy()
    g["open_ms"] = g.index.to_numpy(dtype="int64") * span + offset
    g["close_ms"] = g.open_ms + span
    return g.reset_index(drop=True)


def indicators(bars: pd.DataFrame, preset: str, donchian: int) -> dict:
    h, l, c = bars.high, bars.low, bars.close
    out = {}
    per = ICHIMOKU[preset]
    if per:
        mid = lambda w: (h.rolling(w).max() + l.rolling(w).min()) / 2
        ten, kij, sb = mid(per[0]), mid(per[1]), mid(per[2])
        sa = ((ten + kij) / 2).shift(per[3])
        sb = sb.shift(per[3])
        out["kumo_top"] = np.fmax(sa, sb).where(sa.notna() & sb.notna())
        out["kumo_bot"] = np.fmin(sa, sb).where(sa.notna() & sb.notna())
        out["kijun"] = kij
    else:
        out["kumo_top"] = pd.Series(-np.inf, index=bars.index)
        out["kumo_bot"] = pd.Series(np.inf, index=bars.index)
        out["kijun"] = (h.rolling(26).max() + l.rolling(26).min()) / 2
    out["don_hi"] = h.rolling(donchian).max().shift(1)
    out["don_lo"] = l.rolling(donchian).min().shift(1)
    tr = pd.concat([h - l, (h - c.shift(1)).abs(), (l - c.shift(1)).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    out["atr"] = atr
    out["atr_med"] = atr.rolling(60).median().shift(1)
    out["tr10_lo"], out["tr10_hi"] = l.rolling(10).min(), h.rolling(10).max()
    out["tr20_lo"], out["tr20_hi"] = l.rolling(20).min(), h.rolling(20).max()
    out["ch_lo"] = c.rolling(22).max() - 3 * atr
    out["ch_hi"] = c.rolling(22).min() + 3 * atr
    return {k: np.asarray(v, dtype=float) for k, v in out.items()}


def swap_tables(times: np.ndarray, markup_pct: float):
    """Daily long/short swap as annual fraction of USD notional, per pair."""
    d0 = int(times[0] // DAY_MS) - 1
    d1 = int(times[-1] // DAY_MS) + 2
    days = np.arange(d0, d1)
    dates = pd.to_datetime(days * DAY_MS, unit="ms")

    def series(ccy):
        tab = POLICY_RATES[ccy]
        when = pd.to_datetime([d for d, _ in tab])
        idx = np.searchsorted(when.values, dates.values, side="right") - 1
        return np.array([tab[max(i, 0)][1] for i in idx])

    rates = {c: series(c) for c in POLICY_RATES}
    long_ = np.zeros((len(PAIRS), len(days)))
    short = np.zeros((len(PAIRS), len(days)))
    for p, pair in enumerate(PAIRS):
        diff = rates[pair[:3]] - rates[pair[3:]]
        long_[p] = (diff - markup_pct) / 100
        short[p] = (-diff - markup_pct) / 100
    return d0, long_, short


@dataclass
class Prepared:
    times: np.ndarray
    ohlc: np.ndarray
    frames: dict
    bars: dict = field(default_factory=dict)      # (tf) -> list per pair
    ind: dict = field(default_factory=dict)       # (tf, preset, N) -> list per pair dicts
    act: dict = field(default_factory=dict)       # tf -> (act, lag)


def prepare(data_dir: Path) -> Prepared:
    times, ohlc, frames = load_minutes(data_dir)
    return Prepared(times, ohlc, frames)


def bar_arrays(pr: Prepared, tf: str, preset: str, N: int):
    if tf not in pr.bars:
        pr.bars[tf] = [make_bars(pr.frames[p], tf) for p in PAIRS]
        B = max(len(b) for b in pr.bars[tf])
        act = np.full((len(PAIRS), len(pr.times)), -1, dtype=np.int32)
        lag = np.zeros((len(PAIRS), len(pr.times)), dtype=np.int64)
        for p, b in enumerate(pr.bars[tf]):
            close_ms = b.close_ms.to_numpy()
            own = pr.frames[PAIRS[p]].timestamp.to_numpy()
            j = np.searchsorted(own, close_ms)
            ok = j < len(own)
            idx = np.full(len(close_ms), len(pr.times))
            idx[ok] = np.searchsorted(pr.times, own[j[ok]])
            # first available minute at/after the close (several bars may map to
            # the same minute across a weekend: keep the latest one)
            act[p, idx[ok]] = np.arange(len(b))[ok]
            lag[p, idx[ok]] = pr.times[idx[ok]] - close_ms[ok]
        pr.act[tf] = (act, lag, B)
    k = (tf, preset, N)
    if k not in pr.ind:
        pr.ind[k] = [indicators(b, preset, N) for b in pr.bars[tf]]
    return pr.bars[tf], pr.ind[k], pr.act[tf]


def signal_arrays(pr: Prepared, c: Config):
    bars, ind, (act, lag, B) = bar_arrays(pr, c.tf, c.preset, c.donchian)
    P = len(PAIRS)
    sig = np.zeros((P, B), dtype=np.int8)
    stop = np.full((P, B), np.nan)
    trL = np.full((P, B), np.nan)
    trS = np.full((P, B), np.nan)
    kij = np.full((P, B), np.nan)
    cls = np.full((P, B), np.nan)
    for p in range(P):
        x, b = ind[p], bars[p]
        n = len(b)
        close = b.close.to_numpy()
        valid = np.isfinite(x["don_hi"]) & np.isfinite(x["atr"]) & ~np.isnan(x["kumo_top"]) & ~np.isnan(x["kumo_bot"])
        if c.atr_gate:
            valid &= np.isfinite(x["atr_med"]) & (x["atr"] >= x["atr_med"])
        up = valid & (close > np.fmax(x["kumo_top"], x["don_hi"]))
        dn = valid & (close < np.fmin(x["kumo_bot"], x["don_lo"]))
        s = np.where(up, 1, np.where(dn, -1, 0)).astype(np.int8)
        sig[p, :n] = s
        stop[p, :n] = close - s * c.atr_mult * x["atr"]
        name = {"DON10": "tr10", "DON20": "tr20", "DON10_KIJUN": "tr10", "CHAND3": "ch"}[c.trail]
        trL[p, :n], trS[p, :n] = x[f"{name}_lo"], x[f"{name}_hi"]
        if c.trail == "DON10_KIJUN":
            kij[p, :n] = x["kijun"]
        cls[p, :n] = close
    return sig, stop, trL, trS, kij, cls, act, lag


# ----------------------------------------------------------------- engine
@njit(cache=True)
def _conv(p_quote_jpy, price):
    return 1.0 / price if p_quote_jpy else 1.0


@njit(cache=True)
def _notional_usd(base_usd, qty, price):
    return qty if base_usd else qty * price


@njit(cache=True)
def simulate(times, O, H, L, C, act, lag, sig, stop_lvl, trL, trS, kij, cls,
             spread, slip, pip, quote_jpy, base_usd, usd_dir_sign,
             swap_d0, swap_long, swap_short,
             comm_side, lev_cap, risk, min_stop, min_stop_pct,
             use_floor, floor_trig, floor_lock, pyramid, session, weekend_flat,
             usd_cap, daily_loss, i0, i1, max_lag):
    P = O.shape[0]
    # position legs: [side, entry, qty, stop, R, entry_ms, fee_paid, swap_acc, trade_id]
    pos = np.zeros((P, 2, 9))
    floor_next = np.zeros(P, dtype=np.bool_)
    floor_done = np.zeros(P, dtype=np.bool_)
    eligible_add = np.zeros(P, dtype=np.bool_)
    added = np.zeros(P, dtype=np.bool_)
    last = np.full(P, np.nan)
    cap = 200000
    trades = np.zeros((cap, 12))  # pair, side, entry_ms, exit_ms, entry, exit, qty, net, swap, reason, leg, R_usd
    nt = 0
    realised = np.zeros((cap, 2))
    nr = 0
    first_r = 0
    ndays = (times[i1 - 1] - times[i0]) // 86400000 + 3
    curve = np.full((ndays, 2), np.nan)
    balance = 10000.0
    peak = balance
    maxdd = 0.0
    prev_t = times[i0]
    day0 = times[i0] // 86400000
    flat_done_day = -1
    exposure_time = 0
    for i in range(i0, i1):
        t = times[i]
        # ---- swap at 22:00 UTC rollovers (Mon-Fri, Wednesday x3)
        r_prev = (prev_t - 79200000) // 86400000
        r_now = (t - 79200000) // 86400000
        if r_now > r_prev and i > i0:
            for r in range(r_prev + 1, r_now + 1):
                cal_day = r  # rollover at 22:00 UTC of calendar day r
                dow = (cal_day + 3) % 7  # 0 = Monday
                if dow >= 5:
                    continue
                mult = 3.0 if dow == 2 else 1.0
                di = cal_day - swap_d0
                for p in range(P):
                    for leg in range(2):
                        if pos[p, leg, 0] == 0:
                            continue
                        px = last[p]
                        notion = _notional_usd(base_usd[p], pos[p, leg, 2], px)
                        rate = swap_long[p, di] if pos[p, leg, 0] > 0 else swap_short[p, di]
                        flow = notion * rate / 365.0 * mult
                        balance += flow
                        pos[p, leg, 7] += flow
        prev_t = t
        days = t // 86400000
        dow_now = (days + 3) % 7
        hour = (t % 86400000) // 3600000
        for p in range(P):
            if not np.isnan(C[p, i]):
                last[p] = C[p, i]

        # ---- bar-close events: trail / kijun exit / entries
        for p in range(P):
            b = act[p, i]
            if b < 0 or np.isnan(O[p, i]):
                continue
            side = pos[p, 0, 0]
            if side != 0:
                # Kijun close exit (hybrid)
                if not np.isnan(kij[p, b]) and side * (cls[p, b] - kij[p, b]) < 0:
                    raw = O[p, i] if side > 0 else O[p, i] + spread[p]
                    balance, nt, nr = _close_all(p, raw, t, 2.0, pos, trades, nt, realised, nr, balance,
                                                 slip[p], quote_jpy[p], base_usd[p], comm_side)
                    floor_next[p] = False; floor_done[p] = False; eligible_add[p] = False; added[p] = False
                    continue
                lvl = trL[p, b] if side > 0 else trS[p, b]
                if not np.isnan(lvl):
                    for leg in range(2):
                        if pos[p, leg, 0] != 0:
                            if side > 0:
                                pos[p, leg, 3] = max(pos[p, leg, 3], lvl)
                            else:
                                pos[p, leg, 3] = min(pos[p, leg, 3], lvl)
                if pyramid and not added[p] and side * (pos[p, 0, 3] - pos[p, 0, 1]) > 0:
                    if side * (cls[p, b] - pos[p, 0, 1]) >= 2.0 * pos[p, 0, 4]:
                        eligible_add[p] = True
            s = sig[p, b]
            if s == 0 or lag[p, i] > max_lag:
                continue
            if session and (hour < 7 or hour >= 20):
                continue
            if weekend_flat and dow_now == 4 and hour >= 16:
                continue
            if dow_now >= 5:
                continue
            scale = False
            if side != 0:
                if not (pyramid and eligible_add[p] and not added[p] and s == side):
                    continue
                scale = True
            # equity / exposure
            eq = balance
            gross = 0.0
            same_usd = 0
            for q in range(P):
                for leg in range(2):
                    if pos[q, leg, 0] != 0:
                        px = last[q]
                        eq += pos[q, leg, 0] * ((px if pos[q, leg, 0] > 0 else px + spread[q]) - pos[q, leg, 1]) \
                            * pos[q, leg, 2] * _conv(quote_jpy[q], px)
                        gross += _notional_usd(base_usd[q], pos[q, leg, 2], px)
                if pos[q, 0, 0] != 0 and q != p and pos[q, 0, 0] * usd_dir_sign[q] == s * usd_dir_sign[p]:
                    same_usd += 1
            if not scale and same_usd >= usd_cap:
                continue
            while first_r < nr and realised[first_r, 0] < t - 86400000:
                first_r += 1
            dpnl = 0.0
            for j in range(first_r, nr):
                dpnl += realised[j, 1]
            if eq <= 0 or dpnl <= -daily_loss * eq:
                continue
            raw = O[p, i] + spread[p] if s > 0 else O[p, i]
            entry = raw + s * slip[p]
            stp = pos[p, 0, 3] if scale else stop_lvl[p, b]
            dist = s * (entry - stp)
            if dist <= 0:
                continue
            if not scale:
                if min_stop_pct > 0:
                    if dist / entry < min_stop_pct:
                        continue
                elif dist < min_stop * pip[p]:
                    continue
            conv = _conv(quote_jpy[p], entry)
            unit_notional = _notional_usd(base_usd[p], 1.0, entry)
            per_unit = dist * conv + 2 * comm_side * unit_notional + spread[p] * conv
            r_amt = eq * risk * (0.5 if scale else 1.0)
            qty = r_amt / per_unit
            room = (lev_cap * eq - gross) / unit_notional
            qty = math.floor(min(qty, room) / 1000.0) * 1000.0
            if qty < 1000:
                continue
            fee = qty * unit_notional * comm_side
            balance -= fee
            leg = 1 if scale else 0
            pos[p, leg, 0] = s; pos[p, leg, 1] = entry; pos[p, leg, 2] = qty; pos[p, leg, 3] = stp
            pos[p, leg, 4] = dist; pos[p, leg, 5] = t; pos[p, leg, 6] = fee; pos[p, leg, 7] = 0.0
            pos[p, leg, 8] = dist * conv * qty
            if scale:
                added[p] = True
            else:
                floor_next[p] = False; floor_done[p] = False; eligible_add[p] = False; added[p] = False

        # ---- weekend flat
        if weekend_flat and dow_now == 4 and hour >= 20 and flat_done_day != days:
            flat_done_day = days
            for p in range(P):
                if pos[p, 0, 0] != 0 and not np.isnan(O[p, i]):
                    raw = O[p, i] if pos[p, 0, 0] > 0 else O[p, i] + spread[p]
                    balance, nt, nr = _close_all(p, raw, t, 4.0, pos, trades, nt, realised, nr, balance,
                                                 slip[p], quote_jpy[p], base_usd[p], comm_side)
                    floor_next[p] = False; floor_done[p] = False; eligible_add[p] = False; added[p] = False

        # ---- intrabar stops and profit floor (minute resolution)
        for p in range(P):
            side = pos[p, 0, 0]
            if side == 0 or np.isnan(O[p, i]):
                continue
            if floor_next[p]:
                lock = pos[p, 0, 1] + side * floor_lock * pos[p, 0, 4]
                for leg in range(2):
                    if pos[p, leg, 0] != 0:
                        pos[p, leg, 3] = max(pos[p, leg, 3], lock) if side > 0 else min(pos[p, leg, 3], lock)
                floor_next[p] = False
                floor_done[p] = True
            st = pos[p, 0, 3]
            if side > 0:
                o_q, adverse = O[p, i], L[p, i]
                hit = adverse <= st
                raw = min(o_q, st)
            else:
                o_q, adverse = O[p, i] + spread[p], H[p, i] + spread[p]
                hit = adverse >= st
                raw = max(o_q, st)
            if hit:
                balance, nt, nr = _close_all(p, raw, t, 1.0, pos, trades, nt, realised, nr, balance,
                                             slip[p], quote_jpy[p], base_usd[p], comm_side)
                floor_next[p] = False; floor_done[p] = False; eligible_add[p] = False; added[p] = False
                continue
            if use_floor and not floor_done[p]:
                fav = H[p, i] if side > 0 else L[p, i] + spread[p]
                if side * (fav - pos[p, 0, 1]) >= floor_trig * pos[p, 0, 4]:
                    floor_next[p] = True

        # ---- mark-to-market equity & drawdown
        eq = balance
        anyopen = False
        for q in range(P):
            for leg in range(2):
                if pos[q, leg, 0] != 0:
                    anyopen = True
                    px = last[q]
                    mark = px if pos[q, leg, 0] > 0 else px + spread[q]
                    eq += pos[q, leg, 0] * (mark - pos[q, leg, 1]) * pos[q, leg, 2] * _conv(quote_jpy[q], px)
        if anyopen:
            exposure_time += 1
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak
        if dd > maxdd:
            maxdd = dd
        di = days - day0
        curve[di, 0] = days
        curve[di, 1] = eq
        if eq <= 0:
            break
    # close at the end
    for p in range(P):
        if pos[p, 0, 0] != 0:
            raw = last[p] if pos[p, 0, 0] > 0 else last[p] + spread[p]
            balance, nt, nr = _close_all(p, raw, times[i1 - 1], 3.0, pos, trades, nt, realised, nr, balance,
                                         slip[p], quote_jpy[p], base_usd[p], comm_side)
    return balance, maxdd, trades[:nt], curve, exposure_time


@njit(cache=True)
def _close_all(p, raw, t, reason, pos, trades, nt, realised, nr, balance, slip, quote_jpy, base_usd, comm_side):
    for leg in range(2):
        if pos[p, leg, 0] == 0:
            continue
        side = pos[p, leg, 0]
        px = raw - side * slip
        conv = _conv(quote_jpy, px)
        gross = side * (px - pos[p, leg, 1]) * pos[p, leg, 2] * conv
        fee = _notional_usd(base_usd, pos[p, leg, 2], px) * comm_side
        balance += gross - fee
        net = gross - fee - pos[p, leg, 6] + pos[p, leg, 7]
        trades[nt, 0] = p; trades[nt, 1] = side; trades[nt, 2] = pos[p, leg, 5]; trades[nt, 3] = t
        trades[nt, 4] = pos[p, leg, 1]; trades[nt, 5] = px; trades[nt, 6] = pos[p, leg, 2]
        trades[nt, 7] = net; trades[nt, 8] = pos[p, leg, 7]; trades[nt, 9] = reason; trades[nt, 10] = leg
        trades[nt, 11] = pos[p, leg, 8]
        nt += 1
        realised[nr, 0] = t; realised[nr, 1] = gross - fee - pos[p, leg, 6] + pos[p, leg, 7]
        nr += 1
        pos[p, leg, :] = 0.0
    return balance, nt, nr


REASONS = {1.0: "stop", 2.0: "kijun_close", 3.0: "period_end", 4.0: "weekend_flat"}


def ms(day: str) -> int:
    return int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp() * 1000)


def run(pr: Prepared, c: Config, costs: Costs, start: str, end: str, detail: bool = False) -> dict:
    sig, stop, trL, trS, kij, cls, act, lag = signal_arrays(pr, c)
    if not hasattr(pr, "_swap") or pr._swap[0] != costs.swap_markup_pct:
        pr._swap = (costs.swap_markup_pct, *swap_tables(pr.times, costs.swap_markup_pct))
    _, d0, sl, ss = pr._swap
    i0 = int(np.searchsorted(pr.times, ms(start)))
    i1 = int(np.searchsorted(pr.times, ms(end)))
    pip = np.array([PIP[p] for p in PAIRS])
    spread = np.array(costs.spread_pips) * pip
    slip = costs.slippage_pips * pip
    quote_jpy = np.array([p.endswith("JPY") for p in PAIRS])
    base_usd = np.array([p.startswith("USD") for p in PAIRS])
    usd_dir = np.array([1 if p.startswith("USD") else -1 for p in PAIRS], dtype=np.int64)
    min_pct = -c.min_stop_pips / 100 if c.min_stop_pips < 0 else 0.0
    O, H, L, Cc = pr.ohlc
    bal, dd, tr, curve, expo = simulate(
        pr.times, O, H, L, Cc, act, lag, sig, stop, trL, trS, kij, cls,
        spread, slip, pip, quote_jpy, base_usd, usd_dir, d0, sl, ss,
        costs.commission_rt_per_100k / 200_000, costs.leverage_cap, c.risk,
        max(c.min_stop_pips, 0.0), min_pct, c.profit_floor, c.floor_trigger_r, c.floor_lock_r,
        c.pyramid, c.session, c.weekend_flat, c.usd_cap, c.daily_loss, i0, i1,
        TF_MS[c.tf] // 4 if c.tf != "1h" else 5 * MINUTE_MS)
    years = (ms(end) - ms(start)) / DAY_MS / 365.2425
    net = tr[:, 7]
    wins, losses = net[net > 0], net[net < 0]
    curve = curve[~np.isnan(curve[:, 0])]
    eq = pd.Series(curve[:, 1], index=pd.to_datetime(curve[:, 0] * DAY_MS, unit="ms"))
    yearly = {}
    if len(eq):
        ye = eq.groupby(eq.index.year).last()
        prev = SEED
        for y, v in ye.items():
            yearly[int(y)] = round(100 * (v / prev - 1), 2)
            prev = v
    d_ret = eq.pct_change().dropna()
    sharpe = float(d_ret.mean() / d_ret.std() * math.sqrt(252)) if len(d_ret) > 2 and d_ret.std() > 0 else 0.0
    cagr = 100 * ((bal / SEED) ** (1 / years) - 1) if bal > 0 else -100.0
    res = {
        "config": key(c), "start": start, "end": end,
        "final_equity": round(float(bal), 2), "return_pct": round(100 * (bal / SEED - 1), 2),
        "cagr_pct": round(cagr, 2), "max_dd_pct": round(100 * dd, 2),
        "calmar": round(cagr / (100 * dd), 3) if dd > 0 else None,
        "sharpe": round(sharpe, 2), "trades": int(len(tr)),
        "win_rate_pct": round(100 * len(wins) / len(tr), 1) if len(tr) else 0.0,
        "profit_factor": round(float(wins.sum() / -losses.sum()), 2) if len(losses) else None,
        "swap_usd": round(float(tr[:, 8].sum()), 2),
        "exposure_pct": round(100 * expo / max(1, i1 - i0), 1),
        "yearly_pct": yearly,
        "per_pair_net_usd": {PAIRS[p]: round(float(net[tr[:, 0] == p].sum()), 2) for p in range(len(PAIRS))},
        "per_pair_trades": {PAIRS[p]: int((tr[:, 0] == p).sum()) for p in range(len(PAIRS))},
    }
    if detail:
        res["trade_list"] = [{
            "pair": PAIRS[int(r[0])], "side": "long" if r[1] > 0 else "short",
            "entry_utc": datetime.fromtimestamp(r[2] / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M"),
            "exit_utc": datetime.fromtimestamp(r[3] / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M"),
            "entry": round(float(r[4]), 5), "exit": round(float(r[5]), 5), "units": int(r[6]),
            "net_usd": round(float(r[7]), 2), "swap_usd": round(float(r[8]), 2),
            "r_multiple": round(float(r[7] / r[11]), 2) if r[11] > 0 else None,
            "reason": REASONS.get(float(r[9]), "?"), "pyramid_leg": bool(r[10])} for r in tr]
        res["equity_curve"] = [[str(d.date()), round(float(v), 2)] for d, v in eq.items()]
    return res
