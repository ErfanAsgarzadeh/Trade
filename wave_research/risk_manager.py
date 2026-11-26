import numpy as np
from numba import njit


@njit(cache=True)
def single_book(fills, prices, funding, days, risk, leverage, margin_cap, fee, slip, compound):
    """Daily equity including estimated liquidation friction for open trades."""
    daily = np.zeros(days)
    pnl = np.zeros(len(fills))
    quantities = np.zeros(len(fills))
    balance = 10000.
    for i, row in enumerate(fills):
        em, xm, side, entry, _, distance, unit = row[:7]
        if balance <= 0:
            break
        budget = balance if compound else 10000.
        qty = min(budget * risk / (distance + 2 * (fee + slip) * entry),
                  margin_cap * balance * leverage / entry)
        if qty * entry < 20:
            continue
        quantities[i] = qty
        pnl[i] = qty * unit
        first_day, exit_day = int(em)//1440, int(xm)//1440
        for d in range(first_day, exit_day):
            minute = (d + 1) * 1440 - 1
            mark = prices[minute, 3] * (1 - side * slip)
            mark_fee = fee * (entry + mark)
            carry = side * prices[int(em), 0] * (funding[minute + 1] - funding[int(em) + 1])
            daily[d] += qty * (side * (mark - entry) - mark_fee - carry)
        daily[exit_day] += pnl[i]
        balance += pnl[i]
    exits = np.zeros(days)
    for i, row in enumerate(fills):
        exits[int(row[1]) // 1440] += pnl[i]
    return 10000. + np.cumsum(exits) + daily - exits, pnl, quantities
