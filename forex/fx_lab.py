#!/usr/bin/env python3
"""FX strategy lab: many signal families on EURUSD/GBPUSD/USDJPY, minute-level fills.

Every (family, parameters, pair) run produces a *daily mark-to-market P&L stream in R*
(1R = the planned initial risk of a trade, costs included).  Streams are sizing-free,
so thousands of them can be combined into multi-bot portfolios and scaled to any risk
per trade afterwards: equity[d+1] = equity[d] * (1 + risk * sum_i R_i[d]).

Families
    shahin   Donchian breakout outside Kumo, ATR stop, channel/chandelier trail, floor
    mojsavar EMA trend + RSI pull-back cross, follow-through confirm, ATR trail, lock, partial
    ghoghnous key-reversal outside bar, stop-order entry, time stop, opposite exit, vol gate
    bbfade   Bollinger-band fade, exit at the mid band, ATR stop, time stop, trend filter
    rsi2     Connors RSI(2) pull-back in the EMA200 trend, exit on SMA5 cross
    london   Asian-range (00-07 UTC) breakout with OCO stop orders, or fade of a failed break
    tsmom    daily time-series momentum (sign of N-day return) with ATR stop and trail
    insidebar inside-bar breakout with OCO stop orders
"""
from __future__ import annotations

import itertools
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from numba import njit

import shahin_fx as sfx

PAIRS = sfx.PAIRS
DAY_MS, HOUR_MS, MIN_MS = sfx.DAY_MS, sfx.HOUR_MS, sfx.MINUTE_MS


# =================================================================== engine
@njit(cache=True)
def sim(times, O, H, L, C, bar_min, bar_close, atr,
        side, etype, lvlL, stpL, lvlS, stpS, valid_ms,
        trL, trS, xline, oppo,
        trail_mode, chand_k, xdir, time_stop, arm_r, lock_r, part_r, part_frac, tgt_r,
        spread, slip, comm, swapL, swapS, swap_d0, day0, ndays, weekend_flat):
    """One pair, one strategy.  Returns daily R stream, daily max leverage-per-R, trades."""
    daily = np.zeros(ndays)
    levd = np.zeros(ndays)
    trades = np.zeros((20000, 6))   # entry_ms, exit_ms, side, R, lev_per_R, reason
    nt = 0
    # position
    ps = 0; pe = 0.0; pstop = 0.0; pdist = 0.0; prem = 1.0; preal = 0.0; pmark = 0.0
    pbars = 0; pbest = 0.0; pentry_ms = 0; parmed = False; plock_next = False; pparted = False
    plev = 0.0
    # pending order(s)
    o_side = 0; o_lL = 0.0; o_sL = 0.0; o_lS = 0.0; o_sS = 0.0; o_until = 0
    nb = len(bar_min)
    bp = 0  # next bar pointer
    done = -1
    prev_t = times[0]
    for i in range(len(times)):
        t = times[i]
        o, h, l, c = O[i], H[i], L[i], C[i]
        d = t // DAY_MS - day0
        # ---------------- swap at 22:00 UTC (Mon-Fri, Wed x3), in R
        if ps != 0 and i > 0:
            r0 = (prev_t - 79200000) // DAY_MS
            r1 = (t - 79200000) // DAY_MS
            for r in range(r0 + 1, r1 + 1):
                dow = (r + 3) % 7
                if dow >= 5:
                    continue
                rate = swapL[r - swap_d0] if ps > 0 else swapS[r - swap_d0]
                mult = 3.0 if dow == 2 else 1.0
                preal += prem * rate / 365.0 * mult * pe / pdist
        prev_t = t
        reason = 0
        # ---------------- bar events (exits by close rules, trail, signals)
        while bp + 1 < nb and bar_min[bp + 1] <= i:
            bp += 1
        if bp < nb and bar_min[bp] == i and bp != done:
            b = bp
            done = bp
            if ps != 0:
                pbars += 1
                bc = bar_close[b]
                if ps * (bc - pbest) > 0:
                    pbest = bc
                if xdir != 0 and not np.isnan(xline[b]):
                    if xdir > 0 and ps * (bc - xline[b]) >= 0:
                        reason = 2
                    elif xdir < 0 and ps * (bc - xline[b]) < 0:
                        reason = 2
                if reason == 0 and oppo[b] == -ps:
                    reason = 3
                if reason == 0 and time_stop > 0 and pbars >= time_stop:
                    reason = 4
                if reason != 0:
                    px = (o if ps > 0 else o + spread) - ps * slip
                    r_tot = preal + prem * (ps * (px - pe) / pdist - comm * px / pdist)
                    daily[d] += r_tot - pmark
                    trades[nt, 0] = pentry_ms; trades[nt, 1] = t; trades[nt, 2] = ps; trades[nt, 3] = r_tot
                    trades[nt, 4] = plev; trades[nt, 5] = reason; nt += 1
                    ps = 0
                else:
                    if trail_mode == 1:
                        lv = trL[b] if ps > 0 else trS[b]
                        if not np.isnan(lv):
                            pstop = max(pstop, lv) if ps > 0 else min(pstop, lv)
                    elif trail_mode == 2 and not np.isnan(atr[b]):
                        lv = pbest - ps * chand_k * atr[b]
                        pstop = max(pstop, lv) if ps > 0 else min(pstop, lv)
            if ps == 0 and side[b] != 0:
                s = side[b]
                o_side = 0
                if etype[b] == 0:
                    raw = o + spread if s > 0 else o
                    e = raw + s * slip
                    st = stpL[b] if s > 0 else stpS[b]
                    dist = s * (e - st)
                    if dist > 0:
                        ps = s; pe = e; pstop = st; pdist = dist; prem = 1.0
                        preal = -comm * e / dist; pmark = 0.0; pbars = 0; pbest = bar_close[b]
                        pentry_ms = t; parmed = False; plock_next = False; pparted = False
                        plev = e / dist
                else:
                    o_side = s; o_lL = lvlL[b]; o_sL = stpL[b]; o_lS = lvlS[b]; o_sS = stpS[b]
                    o_until = t + valid_ms
        # ---------------- pending stop orders (OCO for side==2)
        if ps == 0 and o_side != 0:
            if t > o_until:
                o_side = 0
            else:
                filled = 0
                if o_side == 1 or o_side == 2:
                    if l <= o_sL and o_side == 1:
                        o_side = 0  # stop level reached first -> cancel
                    elif h + spread >= o_lL:
                        filled = 1
                if filled == 0 and (o_side == -1 or o_side == 2):
                    if h + spread >= o_sS and o_side == -1:
                        o_side = 0
                    elif l <= o_lS:
                        filled = -1
                if filled != 0:
                    if filled > 0:
                        e = max(o + spread, o_lL) + slip; st = o_sL
                    else:
                        e = min(o, o_lS) - slip; st = o_sS
                    dist = filled * (e - st)
                    o_side = 0
                    if dist > 0:
                        ps = filled; pe = e; pstop = st; pdist = dist; prem = 1.0
                        preal = -comm * e / dist; pmark = 0.0; pbars = 0; pbest = e
                        pentry_ms = t; parmed = False; plock_next = False; pparted = False
                        plev = e / dist
        # ---------------- weekend flat
        if ps != 0 and weekend_flat:
            if ((t // DAY_MS) + 3) % 7 == 4 and (t % DAY_MS) >= 20 * HOUR_MS:
                px = (o if ps > 0 else o + spread) - ps * slip
                r_tot = preal + prem * (ps * (px - pe) / pdist - comm * px / pdist)
                daily[d] += r_tot - pmark
                trades[nt, 0] = pentry_ms; trades[nt, 1] = t; trades[nt, 2] = ps; trades[nt, 3] = r_tot
                trades[nt, 4] = plev; trades[nt, 5] = 5; nt += 1
                ps = 0
        # ---------------- intrabar stop / target / lock / partial
        if ps != 0:
            if plock_next:
                lk = pe + ps * lock_r * pdist
                pstop = max(pstop, lk) if ps > 0 else min(pstop, lk)
                plock_next = False
            if ps > 0:
                adv = l; fav = h; oq = o
            else:
                adv = h + spread; fav = l + spread; oq = o + spread
            px = 0.0; why = 0
            if ps * (adv - pstop) <= 0:
                px = min(oq, pstop) if ps > 0 else max(oq, pstop)
                px -= ps * slip; why = 1
            elif tgt_r > 0 and ps * (fav - (pe + ps * tgt_r * pdist)) >= 0:
                px = pe + ps * tgt_r * pdist; why = 6
            if why != 0:
                r_tot = preal + prem * (ps * (px - pe) / pdist - comm * px / pdist)
                daily[d] += r_tot - pmark
                trades[nt, 0] = pentry_ms; trades[nt, 1] = t; trades[nt, 2] = ps; trades[nt, 3] = r_tot
                trades[nt, 4] = plev; trades[nt, 5] = why; nt += 1
                ps = 0
            else:
                move = ps * (fav - pe) / pdist
                if part_r > 0 and not pparted and move >= part_r:
                    px2 = pe + ps * part_r * pdist
                    preal += part_frac * (part_r - comm * px2 / pdist)
                    prem -= part_frac
                    pparted = True
                if arm_r > 0 and not parmed and move >= arm_r:
                    parmed = True; plock_next = True
        # ---------------- daily mark (at the last minute of each day)
        if ps != 0:
            nxt_day = (times[i + 1] // DAY_MS - day0) if i + 1 < len(times) else d + 1
            if nxt_day != d:
                mk = (c if ps > 0 else c + spread)
                v = preal + prem * ps * (mk - pe) / pdist
                daily[d] += v - pmark
                pmark = v
                if plev * prem > levd[d]:
                    levd[d] = plev * prem
    if ps != 0:
        n = len(times) - 1
        px = C[n] if ps > 0 else C[n] + spread
        r_tot = preal + prem * (ps * (px - pe) / pdist - comm * px / pdist)
        daily[times[n] // DAY_MS - day0] += r_tot - pmark
        trades[nt, 0] = pentry_ms; trades[nt, 1] = times[n]; trades[nt, 2] = ps; trades[nt, 3] = r_tot
        trades[nt, 4] = plev; trades[nt, 5] = 7; nt += 1
    return daily, levd, trades[:nt]


# =================================================================== data
class Lab:
    """Minute data + costs for any set of symbols on one shared day axis."""
    START, END = "2021-11-12", "2026-11-08"

    def __init__(self, data_dir: Path, symbols=PAIRS):
        import instruments as ins
        self.symbols = tuple(symbols)
        self.spec = {s: ins.SPEC[s] for s in self.symbols}
        lo, hi = sfx.ms(self.START), sfx.ms(self.END)
        self.min = {}
        for p in self.symbols:
            f = pd.read_csv(data_dir / "ohlcv" / f"{p[:3]}_{p[3:]}_bid_1m.csv")
            f = f[(f.timestamp >= lo) & (f.timestamp < hi)]
            self.min[p] = {k: f[k].to_numpy(dtype=np.float64) for k in ("open", "high", "low", "close")}
            self.min[p]["t"] = f.timestamp.to_numpy(dtype=np.int64)
        self.day0 = lo // DAY_MS
        self.ndays = (hi - lo) // DAY_MS + 1
        self.swap_d0, self.swapL, self.swapS = ins.swap_tables(self.symbols, lo, hi)
        self.bars = {}

    def get_bars(self, pair, tf):
        k = (pair, tf)
        if k not in self.bars:
            m = self.min[pair]
            fr = pd.DataFrame({"timestamp": m["t"], "open": m["open"], "high": m["high"],
                               "low": m["low"], "close": m["close"]})
            b = sfx.make_bars(fr, tf)
            b["bar_min"] = np.searchsorted(m["t"], b.close_ms.to_numpy())
            b["lag"] = np.where(b.bar_min < len(m["t"]),
                                m["t"][np.minimum(b.bar_min, len(m["t"]) - 1)] - b.close_ms, 10 ** 12)
            h, l, c = b.high, b.low, b.close
            tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
            b["atr"] = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
            b["hour"] = (b.close_ms % DAY_MS) // HOUR_MS
            b["dow"] = ((b.close_ms // DAY_MS) + 3) % 7
            self.bars[k] = b
        return self.bars[k]

    def run(self, pair, tf, sig: dict, ex: dict):
        b = self.get_bars(pair, tf)
        m = self.min[pair]
        n = len(b)
        pip, spread, slip, comm = self.spec[pair]
        nan = np.full(n, np.nan)
        side = sig["side"].astype(np.int8).copy()
        # no fresh entry when the bar close is stale (weekend / holiday gap) or on weekend closes
        max_lag = 5 * MIN_MS if tf == "1h" else HOUR_MS
        side[(b.lag.to_numpy() > max_lag)] = 0
        if ex.get("session"):
            hr = b.hour.to_numpy()
            side[(hr < 7) | (hr >= 20)] = 0
        if ex.get("weekend_flat"):
            side[(b.dow.to_numpy() == 4) & (b.hour.to_numpy() >= 16)] = 0
        etype = sig.get("etype", np.zeros(n, np.int8)).astype(np.int8)
        stpL = sig.get("stpL", nan); stpS = sig.get("stpS", nan)
        lvlL = sig.get("lvlL", nan); lvlS = sig.get("lvlS", nan)
        # minimum stop distance (pips) for market entries
        ms = ex.get("min_stop_pips", 3.0) * pip
        close = b.close.to_numpy()
        bad = ((side == 1) & (close - stpL < ms)) | ((side == -1) & (stpS - close < ms)) | \
              ((side == 2) & ((lvlL - stpL < ms) | (stpS - lvlS < ms)))
        side[bad] = 0
        daily, levd, tr = sim(
            m["t"], m["open"], m["high"], m["low"], m["close"],
            b.bar_min.to_numpy(np.int64), close, b.atr.to_numpy(),
            side, etype, lvlL, stpL, lvlS, stpS, int(sig.get("valid_ms", 0)),
            sig.get("trL", nan), sig.get("trS", nan), sig.get("xline", nan),
            sig.get("oppo", np.zeros(n, np.int8)).astype(np.int8),
            int(ex.get("trail_mode", 0)), float(ex.get("chand_k", 3.0)), int(ex.get("xdir", 0)),
            int(ex.get("time_stop", 0)), float(ex.get("arm_r", 0)), float(ex.get("lock_r", 0)),
            float(ex.get("part_r", 0)), float(ex.get("part_frac", 0.5)), float(ex.get("tgt_r", 0)),
            spread, slip, comm,
            self.swapL[pair], self.swapS[pair], self.swap_d0, self.day0, self.ndays,
            bool(ex.get("weekend_flat", False)))
        return daily, levd, tr


# =================================================================== indicators
def ema(x, n): return x.ewm(span=n, adjust=False).mean()


def rsi(c, n):
    d = c.diff().fillna(0.0)
    g = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    l_ = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + g / l_.where(l_ != 0, 1e-12))


def A(x): return np.asarray(x, dtype=np.float64)


# =================================================================== families
def fam_shahin(b, p):
    h, l, c, atr = b.high, b.low, b.close, b.atr
    per = sfx.ICHIMOKU[p["preset"]]
    if per:
        mid = lambda w: (h.rolling(w).max() + l.rolling(w).min()) / 2
        ten, kij, sb = mid(per[0]), mid(per[1]), mid(per[2])
        sa, sb = ((ten + kij) / 2).shift(per[3]), sb.shift(per[3])
        top, bot = np.fmax(sa, sb), np.fmin(sa, sb)
    else:
        top, bot = pd.Series(-np.inf, index=b.index), pd.Series(np.inf, index=b.index)
    dh, dl = h.rolling(p["N"]).max().shift(1), l.rolling(p["N"]).min().shift(1)
    ok = dh.notna() & atr.notna() & top.notna()
    if p["gate"]:
        ok &= atr >= atr.rolling(60).median().shift(1)
    side = np.where(ok & (c > np.fmax(top, dh)), 1, np.where(ok & (c < np.fmin(bot, dl)), -1, 0))
    tn = p["trailN"]
    return dict(side=side, stpL=A(c - p["atr"] * atr), stpS=A(c + p["atr"] * atr),
                trL=A(l.rolling(tn).min()), trS=A(h.rolling(tn).max()))


def fam_mojsavar(b, p):
    c, atr = b.close, b.atr
    ef, es = ema(c, p["ef"]), ema(c, p["es"])
    r = rsi(c, p["rp"])
    lo, hi = p["rl"], 100 - p["rl"]
    raw = np.where((ef > es) & (r.shift() <= lo) & (r > lo), 1,
                   np.where((ef < es) & (r.shift() >= hi) & (r < hi), -1, 0))
    if p["confirm"] > 0:  # follow-through: a later close beyond the signal close within N bars
        side = np.zeros(len(c), int)
        cc, trend = c.to_numpy(), np.sign((ef - es).to_numpy())
        pend = []
        for i in range(len(c)):
            keep, hit = [], 0
            for (s, lvl, dl) in pend:
                if trend[i] != s:
                    continue
                if s * (cc[i] - lvl) > 0:
                    hit = s
                    continue
                if i < dl:
                    keep.append((s, lvl, dl))
            if raw[i]:
                keep.append((raw[i], cc[i], i + p["confirm"]))
            pend = keep
            side[i] = hit
    else:
        side = raw
    return dict(side=side, stpL=A(c - p["stop"] * atr), stpS=A(c + p["stop"] * atr))


def fam_ghoghnous(b, p):
    h, l, c, atr = b.high, b.low, b.close, b.atr
    n = p["lb"]
    rng = (h - l).clip(lower=1e-12)
    outside = (h > h.shift()) & (l < l.shift())
    big = rng >= p["minr"] * atr
    lowest = l <= l.rolling(n + 1).min()
    highest = h >= h.rolling(n + 1).max()
    L_ = outside & big & lowest & (c > c.shift()) & ((c - l) / rng >= p["cf"])
    S_ = outside & big & highest & (c < c.shift()) & ((h - c) / rng >= p["cf"])
    raw = np.where(L_, 1, np.where(S_, -1, 0))
    side = raw.copy()
    if p["vgate"] < 1:
        x = (atr / c).to_numpy()
        vr = pd.Series(x).rolling(500).apply(lambda w: (w[:-1] < w[-1]).mean(), raw=True).to_numpy()
        side[~(vr < p["vgate"])] = 0
    buf = 0.1 * atr
    out = dict(side=side, etype=np.ones(len(c)), lvlL=A(h), stpL=A(l - buf), lvlS=A(l), stpS=A(h + buf),
               valid_ms=sfx.TF_MS[p["tf"]])
    if p["oppo"]:
        out["oppo"] = raw
    return out


def fam_bbfade(b, p):
    c, atr = b.close, b.atr
    m = c.rolling(p["n"]).mean()
    sd = c.rolling(p["n"]).std()
    up, dn = m + p["k"] * sd, m - p["k"] * sd
    side = np.where(c < dn, 1, np.where(c > up, -1, 0))
    if p["trend"] == "with":
        e = ema(c, 200)
        side = np.where(((side == 1) & (c > e)) | ((side == -1) & (c < e)), side, 0)
    elif p["trend"] == "flat":  # only when the long-term trend is weak
        e = ema(c, 200)
        flat = (abs(c - e) < 2 * atr)
        side = np.where(flat, side, 0)
    return dict(side=side, stpL=A(c - p["stop"] * atr), stpS=A(c + p["stop"] * atr), xline=A(m))


def fam_rsi2(b, p):
    c, atr = b.close, b.atr
    r = rsi(c, 2)
    e = ema(c, 200)
    side = np.where((c > e) & (r < p["lo"]), 1, np.where((c < e) & (r > 100 - p["lo"]), -1, 0))
    return dict(side=side, stpL=A(c - p["stop"] * atr), stpS=A(c + p["stop"] * atr),
                xline=A(c.rolling(5).mean()))


def fam_london(b, p):
    """1h bars. Asian range = bars closing 01..07 UTC; act at the 07:00 UTC close."""
    h, l, c, atr = b.high, b.low, b.close, b.atr
    hr = b.hour.to_numpy()
    rh = h.rolling(p["hours"]).max()
    rl = l.rolling(p["hours"]).min()
    width = rh - rl
    at = (hr == p["at"])
    ok = at & (width < p["maxw"] * atr * math.sqrt(24)) & (width > 0)
    if p["mode"] == "break":
        side = np.where(ok, 2, 0)
        stpL = rl + (rh - rl) * p["stopfrac"]
        stpS = rh - (rh - rl) * p["stopfrac"]
        return dict(side=side, etype=np.ones(len(c)), lvlL=A(rh), stpL=A(stpL), lvlS=A(rl), stpS=A(stpS),
                    valid_ms=p["valid_h"] * HOUR_MS)
    # fade: price already broke out of the range during the session and closed back inside
    prev_rh, prev_rl = rh.shift(p["lag"]), rl.shift(p["lag"])
    hr_ok = np.isin(hr, p["fade_hours"])
    brokeup = (h.rolling(p["lag"]).max() > prev_rh) & (c < prev_rh)
    brokedn = (l.rolling(p["lag"]).min() < prev_rl) & (c > prev_rl)
    side = np.where(hr_ok & brokeup, -1, np.where(hr_ok & brokedn, 1, 0))
    return dict(side=side, stpL=A(l.rolling(p["lag"]).min() - 0.1 * atr),
                stpS=A(h.rolling(p["lag"]).max() + 0.1 * atr), xline=A((prev_rh + prev_rl) / 2))


def fam_tsmom(b, p):
    c, atr = b.close, b.atr
    mom = np.sign(c - c.shift(p["n"])).fillna(0)
    flip = mom != mom.shift()
    side = np.where(flip, mom, 0).astype(int)
    return dict(side=side, stpL=A(c - p["stop"] * atr), stpS=A(c + p["stop"] * atr), oppo=mom.fillna(0).to_numpy())


def fam_insidebar(b, p):
    h, l, c, atr = b.high, b.low, b.close, b.atr
    inside = (h < h.shift()) & (l > l.shift())
    if p["trend"]:
        e = ema(c, 200)
        sideval = np.where(c > e, 1, -1)
    else:
        sideval = np.full(len(c), 2)
    side = np.where(inside & (h - l > 0.3 * atr), sideval, 0)
    return dict(side=side, etype=np.ones(len(c)), lvlL=A(h), stpL=A(l - 0.1 * atr), lvlS=A(l),
                stpS=A(h + 0.1 * atr), valid_ms=p["valid"] * sfx.TF_MS[p["tf"]])


def grid_dict(**kw):
    keys = list(kw)
    for vals in itertools.product(*kw.values()):
        yield dict(zip(keys, vals))


def families():
    """Yield (family, tf, signal-params, exit-params)."""
    # ---- Shahin
    for tf in ("4h", "D1"):
        for sp in grid_dict(preset=("standard", "none"), N=(10, 20, 55), atr=(2.0, 3.0), gate=(True, False),
                            trailN=(10, 20)):
            for ex in ({"trail_mode": 1}, {"trail_mode": 1, "arm_r": 1.0, "lock_r": 0.5},
                       {"trail_mode": 2, "chand_k": 4.0, "arm_r": 1.0, "lock_r": 0.1}):
                yield "shahin", tf, sp, ex
    # ---- Mojsavar (C3+D)
    for tf in ("1h", "4h", "D1"):
        for sp in grid_dict(ef=(20, 50), es=(100, 200), rp=(14, 7), rl=(40.0, 30.0), confirm=(0, 3), stop=(1.5, 2.0, 3.0)):
            if sp["ef"] >= sp["es"]:
                continue
            for ex in ({"trail_mode": 2, "chand_k": 4.5, "arm_r": 1.0, "lock_r": 0.1, "part_r": 2.0},
                       {"trail_mode": 2, "chand_k": 3.0},
                       {"tgt_r": 2.0}, {"tgt_r": 1.0, "time_stop": 20}):
                yield "mojsavar", tf, sp, ex
    # ---- Ghoghnous (key reversal)
    for tf in ("1h", "4h", "D1"):
        for sp in grid_dict(lb=(10, 20), cf=(0.5, 0.75), minr=(0.0, 1.1), vgate=(1.0, 0.35), oppo=(True, False)):
            sp["tf"] = tf
            for ex in ({"time_stop": 30}, {"time_stop": 10}, {"tgt_r": 2.0, "time_stop": 30},
                       {"tgt_r": 1.0, "time_stop": 10}):
                yield "ghoghnous", tf, sp, ex
    # ---- Bollinger fade
    for tf in ("1h", "4h", "D1"):
        for sp in grid_dict(n=(20, 50), k=(2.0, 2.5, 3.0), stop=(1.5, 2.5, 4.0), trend=("none", "with", "flat")):
            for ex in ({"xdir": 1, "time_stop": 10}, {"xdir": 1, "time_stop": 30}, {"xdir": 1, "tgt_r": 1.0, "time_stop": 20}):
                yield "bbfade", tf, sp, ex
            for ex in ({"xdir": 1, "time_stop": 10, "session": True},):
                if tf == "1h":
                    yield "bbfade", tf, sp, ex
    # ---- RSI(2)
    for tf in ("1h", "4h", "D1"):
        for sp in grid_dict(lo=(5.0, 10.0, 20.0), stop=(1.5, 2.5, 4.0)):
            for ex in ({"xdir": 1, "time_stop": 10}, {"xdir": 1, "time_stop": 5}, {"xdir": 1, "tgt_r": 1.0, "time_stop": 10}):
                yield "rsi2", tf, sp, ex
    # ---- London / Asian range
    for sp in grid_dict(mode=("break",), hours=(6, 7, 8), at=(7, 8), maxw=(0.6, 1.0, 9.0), stopfrac=(0.0, 0.5),
                        valid_h=(4, 8)):
        for ex in ({"time_stop": 13}, {"tgt_r": 1.0, "time_stop": 13}, {"tgt_r": 2.0, "time_stop": 13},
                   {"time_stop": 13, "arm_r": 1.0, "lock_r": 0.1}):
            yield "london", "1h", sp, ex
    for sp in grid_dict(mode=("fade",), hours=(7, 8), at=(7,), maxw=(0.6, 1.0, 9.0), lag=(2, 3, 4),
                        fade_hours=((9, 10, 11), (9, 10, 11, 12, 13, 14, 15))):
        for ex in ({"xdir": 1, "time_stop": 8}, {"tgt_r": 1.0, "time_stop": 8}, {"tgt_r": 2.0, "time_stop": 12}):
            yield "london", "1h", sp, ex
    # ---- TSMOM daily
    for sp in grid_dict(n=(10, 20, 50, 100, 200), stop=(2.0, 3.0, 5.0)):
        for ex in ({}, {"trail_mode": 2, "chand_k": 4.0}, {"trail_mode": 2, "chand_k": 6.0}):
            yield "tsmom", "D1", sp, ex
    # ---- inside bar
    for tf in ("1h", "4h", "D1"):
        for sp in grid_dict(trend=(True, False), valid=(1, 3)):
            sp["tf"] = tf
            for ex in ({"tgt_r": 1.0, "time_stop": 20}, {"tgt_r": 2.0, "time_stop": 20},
                       {"trail_mode": 2, "chand_k": 3.0, "time_stop": 40}):
                yield "insidebar", tf, sp, ex


FAM = {"shahin": fam_shahin, "mojsavar": fam_mojsavar, "ghoghnous": fam_ghoghnous, "bbfade": fam_bbfade,
       "rsi2": fam_rsi2, "london": fam_london, "tsmom": fam_tsmom, "insidebar": fam_insidebar}


# =================================================================== extra technical / price-action families
@njit(cache=True)
def _supertrend(h, l, c, atr, mult):
    n = len(c)
    d = np.zeros(n)
    up = np.full(n, np.nan)
    dn = np.full(n, np.nan)
    for i in range(n):
        if np.isnan(atr[i]):
            continue
        m = (h[i] + l[i]) / 2
        u, w = m + mult * atr[i], m - mult * atr[i]
        if i > 0 and not np.isnan(up[i - 1]):
            u = min(u, up[i - 1]) if c[i - 1] <= up[i - 1] else u
            w = max(w, dn[i - 1]) if c[i - 1] >= dn[i - 1] else w
            if d[i - 1] >= 0:
                d[i] = -1.0 if c[i] < w else 1.0
            else:
                d[i] = 1.0 if c[i] > u else -1.0
        else:
            d[i] = 1.0
        up[i], dn[i] = u, w
    return d


def _flip(x):
    x = pd.Series(x).fillna(0)
    return np.where((x != x.shift()) & (x != 0), x, 0).astype(int)


def _trend_ok(side, c, use):
    if not use:
        return side
    e = ema(c, 200).to_numpy()
    cc = c.to_numpy()
    return np.where(((side == 1) & (cc > e)) | ((side == -1) & (cc < e)), side, 0)


def _stops(c, atr, k):
    return dict(stpL=A(c - k * atr), stpS=A(c + k * atr))


def fam_macd(b, p):
    c, atr = b.close, b.atr
    m = ema(c, p["f"]) - ema(c, p["s"])
    sg = ema(m, p["g"])
    pos = np.sign(m - sg).fillna(0).to_numpy()
    side = _flip(pos)
    if p["zero"]:
        mm = m.to_numpy()
        side = np.where(((side == 1) & (mm < 0)) | ((side == -1) & (mm > 0)), side, 0)
    side = _trend_ok(side, c, p["trend"])
    return dict(side=side, oppo=pos.astype(int), **_stops(c, atr, p["stop"]))


def fam_supertrend(b, p):
    d = _supertrend(b.high.to_numpy(), b.low.to_numpy(), b.close.to_numpy(),
                    b.atr.to_numpy() if p["n"] == 14 else
                    b.high.sub(b.low).rolling(p["n"]).mean().to_numpy(), p["mult"])
    side = _flip(d)
    return dict(side=side, oppo=d.astype(int), **_stops(b.close, b.atr, p["stop"]))


def fam_keltner(b, p):
    c, atr = b.close, b.atr
    mid = ema(c, p["n"])
    side = np.where(c > mid + p["k"] * atr, 1, np.where(c < mid - p["k"] * atr, -1, 0))
    side = _flip(side)
    return dict(side=side, xline=A(mid), **_stops(c, atr, p["stop"]))


def fam_stoch(b, p):
    h, l, c, atr = b.high, b.low, b.close, b.atr
    k = 100 * (c - l.rolling(14).min()) / (h.rolling(14).max() - l.rolling(14).min()).replace(0, np.nan)
    k = k.rolling(3).mean()
    lo = p["lvl"]
    side = np.where((k.shift() < lo) & (k >= lo), 1, np.where((k.shift() > 100 - lo) & (k <= 100 - lo), -1, 0))
    side = _trend_ok(side, c, p["trend"])
    return dict(side=side, **_stops(c, atr, p["stop"]))


def fam_macross(b, p):
    c = b.close
    f = ema(c, p["f"]) if p["type"] == "ema" else c.rolling(p["f"]).mean()
    s = ema(c, p["s"]) if p["type"] == "ema" else c.rolling(p["s"]).mean()
    pos = np.sign(f - s).fillna(0).to_numpy()
    return dict(side=_flip(pos), oppo=pos.astype(int), **_stops(c, b.atr, p["stop"]))


def fam_adx(b, p):
    h, l, c, atr = b.high, b.low, b.close, b.atr
    upm, dnm = h.diff(), -l.diff()
    pdm = np.where((upm > dnm) & (upm > 0), upm, 0.0)
    ndm = np.where((dnm > upm) & (dnm > 0), dnm, 0.0)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr14 = tr.ewm(alpha=1 / 14, adjust=False).mean()
    pdi = 100 * pd.Series(pdm, index=c.index).ewm(alpha=1 / 14, adjust=False).mean() / atr14
    ndi = 100 * pd.Series(ndm, index=c.index).ewm(alpha=1 / 14, adjust=False).mean() / atr14
    adx = (100 * (pdi - ndi).abs() / (pdi + ndi).replace(0, np.nan)).ewm(alpha=1 / 14, adjust=False).mean()
    dh, dl = h.rolling(p["N"]).max().shift(), l.rolling(p["N"]).min().shift()
    ok = adx > p["thr"]
    side = np.where(ok & (c > dh), 1, np.where(ok & (c < dl), -1, 0))
    return dict(side=side, trL=A(l.rolling(p["N"] // 2).min()), trS=A(h.rolling(p["N"] // 2).max()),
                **_stops(c, atr, p["stop"]))


def fam_heikin(b, p):
    o, h, l, c = b.open, b.high, b.low, b.close
    hc = (o + h + l + c) / 4
    ho = hc.copy()
    hov = ho.to_numpy().copy()
    hcv = hc.to_numpy()
    ov = o.to_numpy()
    hov[0] = ov[0]
    for i in range(1, len(hov)):
        hov[i] = (hov[i - 1] + hcv[i - 1]) / 2
    col = np.sign(hcv - hov)
    run = pd.Series(col).rolling(p["run"]).sum().to_numpy()
    side = np.where(run == p["run"], 1, np.where(run == -p["run"], -1, 0))
    side = _trend_ok(_flip(side), c, p["trend"])
    return dict(side=side, oppo=col.astype(int), **_stops(c, b.atr, p["stop"]))


def fam_pinbar(b, p):
    o, h, l, c, atr = b.open, b.high, b.low, b.close, b.atr
    rng = (h - l).replace(0, np.nan)
    low_wick = np.minimum(o, c) - l
    up_wick = h - np.maximum(o, c)
    bull = (low_wick / rng >= 0.6) & (l <= l.rolling(p["lb"]).min()) & (rng > 0.8 * atr)
    bear = (up_wick / rng >= 0.6) & (h >= h.rolling(p["lb"]).max()) & (rng > 0.8 * atr)
    side = np.where(bull, 1, np.where(bear, -1, 0))
    buf = 0.1 * atr
    if p["etype"] == "stop":
        return dict(side=side, etype=np.ones(len(c)), lvlL=A(h), stpL=A(l - buf), lvlS=A(l), stpS=A(h + buf),
                    valid_ms=sfx.TF_MS[p["tf"]])
    return dict(side=side, stpL=A(l - buf), stpS=A(h + buf))


def fam_engulf(b, p):
    o, h, l, c, atr = b.open, b.high, b.low, b.close, b.atr
    bull = (c > o) & (c.shift() < o.shift()) & (c >= o.shift()) & (o <= c.shift()) & (l <= l.rolling(p["lb"]).min())
    bear = (c < o) & (c.shift() > o.shift()) & (c <= o.shift()) & (o >= c.shift()) & (h >= h.rolling(p["lb"]).max())
    side = np.where(bull, 1, np.where(bear, -1, 0))
    buf = 0.1 * atr
    return dict(side=side, stpL=A(np.minimum(l, l.shift()) - buf), stpS=A(np.maximum(h, h.shift()) + buf))


_base_families = families


def families():
    yield from _base_families()
    TFS = ("1h", "4h", "D1")
    for tf in TFS:
        for sp in grid_dict(f=(12, 8, 19), s=(26,), g=(9,), zero=(True, False), trend=(True, False), stop=(2.0, 3.0)):
            if sp["f"] == 8:
                sp = dict(sp, s=21, g=5)
            if sp["f"] == 19:
                sp = dict(sp, s=39)
            for ex in ({"trail_mode": 2, "chand_k": 3.0}, {"tgt_r": 2.0, "time_stop": 30}, {}):
                yield "macd", tf, sp, ex
        for sp in grid_dict(n=(14, 20), mult=(2.0, 3.0, 4.0), stop=(2.0, 3.0)):
            for ex in ({}, {"arm_r": 1.0, "lock_r": 0.1}):
                yield "supertrend", tf, sp, ex
        for sp in grid_dict(n=(20, 50), k=(1.5, 2.5), stop=(2.0, 3.0)):
            for ex in ({"xdir": -1}, {"xdir": -1, "trail_mode": 2, "chand_k": 3.0}):
                yield "keltner", tf, sp, ex
        for sp in grid_dict(lvl=(20.0, 10.0), trend=(True, False), stop=(1.5, 3.0)):
            for ex in ({"tgt_r": 1.0, "time_stop": 10}, {"tgt_r": 2.0, "time_stop": 20}):
                yield "stoch", tf, sp, ex
        for sp in grid_dict(f=(10, 20, 50), s=(30,), type=("ema", "sma"), stop=(2.0, 3.0)):
            sp = dict(sp, s={10: 30, 20: 50, 50: 200}[sp["f"]])
            for ex in ({}, {"trail_mode": 2, "chand_k": 4.0}):
                yield "macross", tf, sp, ex
        for sp in grid_dict(N=(20, 55), thr=(20.0, 25.0), stop=(2.0, 3.0)):
            for ex in ({"trail_mode": 1}, {"trail_mode": 1, "arm_r": 1.0, "lock_r": 0.5}):
                yield "adx", tf, sp, ex
        for sp in grid_dict(run=(2, 3), trend=(True, False), stop=(2.0, 3.0)):
            for ex in ({}, {"trail_mode": 2, "chand_k": 3.0}):
                yield "heikin", tf, sp, ex
        for sp in grid_dict(lb=(10, 20), etype=("stop", "market")):
            sp = dict(sp, tf=tf)
            for ex in ({"tgt_r": 1.0, "time_stop": 10}, {"tgt_r": 2.0, "time_stop": 20}, {"trail_mode": 2, "chand_k": 3.0, "time_stop": 30}):
                yield "pinbar", tf, sp, ex
        for sp in grid_dict(lb=(10, 20)):
            for ex in ({"tgt_r": 1.0, "time_stop": 10}, {"tgt_r": 2.0, "time_stop": 20}, {"trail_mode": 2, "chand_k": 3.0, "time_stop": 30}):
                yield "engulf", tf, sp, ex


FAM.update({"macd": fam_macd, "supertrend": fam_supertrend, "keltner": fam_keltner, "stoch": fam_stoch,
            "macross": fam_macross, "adx": fam_adx, "heikin": fam_heikin, "pinbar": fam_pinbar, "engulf": fam_engulf})
