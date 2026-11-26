import numpy as np
from numba import njit


def pack_waves(fills, risk):
    # [entry_min, exit_min, entry, stop_frac, unit, risk, root_index, add]
    return np.column_stack((fills[:, 0], fills[:, 1], fills[:, 3], fills[:, 5]/fills[:, 3],
                            fills[:, 6], np.full(len(fills), risk), np.arange(len(fills)), np.zeros(len(fills))))


def pack_bots(ledger):
    result = {}
    for bot, risk in (("shahin", .01), ("mojsavar", .004), ("ghoghnous", .004)):
        bot_id = {"shahin": "main", "mojsavar": "c3", "ghoghnous": "pa"}[bot]
        roots = {}
        rows = []
        for leg in ledger:
            if leg["bot"] != bot_id:
                continue
            root = roots.setdefault(leg["root"], len(roots))
            rows.append([leg["em"], leg["xm"], leg["entry"], leg["stop_frac"],
                         leg["unit"], risk * leg["risk_scale"], root, int(leg["is_add"])])
        result[bot] = np.array(rows)
    return result


@njit(cache=True)
def _replay(legs, order, days, leverage, cap, denominator_cost, fee):
    n = len(legs)
    cash, margin = 10000., 0.
    notional = np.zeros(n)
    rejected = np.zeros(n, np.bool_)
    pnl = np.zeros(n)
    accepted = np.zeros(n, np.bool_)
    daily = np.zeros(days)
    for event in order:
        i = event % n
        em, xm, entry, distance, unit, risk, root, add = legs[i]
        if event < n:
            if add and rejected[int(root)]:
                continue
            free = max(0., cap * cash - margin) * leverage / (1 + cap * leverage * 2 * fee)
            invest = min(free, risk * cash / (distance + denominator_cost))
            if invest < 20:
                if not add:
                    rejected[int(root)] = True
                continue
            notional[i] = invest
            margin += invest / leverage
            accepted[i] = True
        elif accepted[i]:
            invest = notional[i]
            pnl[i] = invest * unit / entry
            cash += pnl[i]
            daily[int(xm)//1440] += pnl[i]
            margin -= invest / leverage
    return 10000. + np.cumsum(daily), pnl, accepted


def replay(blocks, days, cfg):
    parts = []
    offset = 0
    for block in blocks:
        if not len(block):
            continue
        block = block.copy()
        block[:, 6] += offset
        parts.append(block)
        offset += len(block)
    if not parts:
        return np.full(days, 10000.), np.empty(0), np.empty((0, 2))
    legs = np.concatenate(parts)
    order = np.argsort(np.r_[legs[:, 0], legs[:, 1]], kind="stable")
    f = cfg["friction"]
    curve, pnl, accepted = _replay(legs, order, days, f["leverage"], f["margin_cap"],
                                   2*(f["fee_per_side"] + f["slippage_per_fill"]), f["fee_per_side"])
    exits = order[order >= len(legs)] - len(legs)
    exits = exits[accepted[exits]]
    return curve, pnl[exits], legs[exits, :2]
