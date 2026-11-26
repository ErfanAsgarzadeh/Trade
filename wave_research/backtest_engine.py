import numpy as np
from numba import njit


@njit(cache=True)
def execute(prices, funding, bars, atr, signals, minutes, entry_mode, stop_mode,
            target_r, hold, fee, slip, min_stop, direction=0, confirm=None,
            exit_mode=0, management_r=0.):
    """Columns em, xm, side, entry, exit, distance, unit PnL, unit costs, MAE/R, MFE/R, stop, target."""
    fills = np.empty((np.count_nonzero(signals), 12))
    free, n, pending_until = 0, 0, -1
    for t in range(len(signals) - 1):
        side = signals[t]
        if (side == 0 or (direction and side != direction) or not np.isfinite(atr[t])
                or (t+1)*minutes < free or t <= pending_until):
            continue
        confirmed = t
        if entry_mode in (2, 3, 9, 11, 12):
            confirmed = -1
            for i in range(t + 1, min(t + 4, len(bars)-1)):
                check = False
                if entry_mode == 12:
                    check = side * (bars[i, 3] - bars[t, 3]) >= .3 * atr[t]
                elif confirm is not None:
                    check = confirm[i] == side
                if check:
                    confirmed = i
                    break
            pending_until = confirmed if confirmed >= 0 else t + 3
            if confirmed < 0:
                continue
        entry_minute = (confirmed + 1) * minutes
        if entry_minute < free or entry_minute >= len(prices):
            continue
        raw = prices[entry_minute, 0]
        resting_fill = False
        if entry_mode == 1:
            bar_range = bars[t, 1] - bars[t, 2]
            limit = bars[t, 1] - .618*bar_range if side > 0 else bars[t, 2] + .618*bar_range
            pending_until = t + 3
            hit = -1
            for m in range(entry_minute, min(entry_minute + 3*minutes, len(prices))):
                quote = prices[m, 2 if side > 0 else 1]
                if side * (quote - limit) <= 0:
                    hit = m
                    break
            if hit < 0:
                continue
            entry_minute = hit
            resting_fill = side * (prices[hit, 0] - limit) > 0
            raw = min(prices[hit, 0], limit) if side > 0 else max(prices[hit, 0], limit)
        entry = raw * (1 + side * slip)
        if entry_mode == 1:
            entry = min(entry, limit) if side > 0 else max(entry, limit)
        if stop_mode == 9:
            stop = bars[t, 2 if side > 0 else 1] - side * .1 * atr[t]
        else:
            stop = entry - side * (stop_mode - 2) * .5 * atr[t]
        distance = side * (entry - stop)
        if side * (raw - stop) <= 0 or distance / entry < min_stop:
            continue
        target = entry + side * target_r * distance
        if target <= 0:
            continue
        last = min(entry_minute + hold * minutes, len(prices)) - 1
        exit_minute, exit_raw = last, prices[last, 3]
        adverse, favorable = 0., 0.
        original_stop = stop
        for m in range(entry_minute, last + 1):
            op, hi, lo = prices[m, 0], prices[m, 1], prices[m, 2]
            if m == entry_minute and resting_fill:
                op = raw
            adverse_price = lo if side > 0 else hi
            favorable_price = hi if side > 0 else lo
            if side * (adverse_price - stop) <= 0:
                exit_raw = min(op, stop) if side > 0 else max(op, stop)
                adverse = min(adverse, side * (exit_raw - entry))
                exit_minute = m
                break
            if (exit_mode != 14 and not (m == entry_minute and resting_fill)
                    and side * (favorable_price - target) >= 0):
                exit_raw = max(op, target) if side > 0 else min(op, target)
                favorable = max(favorable, side * (exit_raw - entry))
                exit_minute = m
                break
            adverse = min(adverse, side * (adverse_price - entry))
            if not (m == entry_minute and resting_fill):
                favorable = max(favorable, side * (favorable_price - entry))
            if exit_mode == 17 and favorable >= management_r * distance:
                if side * (entry - stop) > 0:
                    stop = entry
            if exit_mode == 14 and (m+1) % minutes == 0:
                closed_bar = m//minutes
                trailing = prices[m, 3]-side*management_r*atr[closed_bar]
                if side * (trailing-stop) > 0:
                    stop = trailing
        exit_price = exit_raw * (1 - side * slip)
        fees = fee * (entry + exit_price)
        carry = side * raw * (funding[exit_minute + 1] - funding[entry_minute + 1])
        cost = fees + side*(entry - raw) + slip * exit_raw + carry
        unit = side * (exit_price - entry) - fees - carry
        fills[n, 0], fills[n, 1], fills[n, 2] = entry_minute, exit_minute, side
        fills[n, 3], fills[n, 4], fills[n, 5], fills[n, 6], fills[n, 7] = entry, exit_price, distance, unit, cost
        fills[n, 8], fills[n, 9], fills[n, 10], fills[n, 11] = -adverse/distance, favorable/distance, original_stop, target
        n += 1
        free = exit_minute + 1
    return fills[:n]
