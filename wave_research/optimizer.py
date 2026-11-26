from itertools import product

import numpy as np
import pandas as pd


def development_rank(frame, cfg):
    train = frame.loc[(frame.period == "train") & (frame.risk == cfg["baseline"]["risk"])
                      & (frame.sizing == "compound") & (frame.direction == 0)
                      & (frame.trades >= cfg["selection"]["minimum_trades"])
                      & (frame.expectancy_r > 0)].copy()
    train["rank_score"] = train.sharpe - .015 * train.drawdown_pct
    return train.sort_values(["rank_score", "trades", "strategy", "symbol", "timeframe"],
                             ascending=[False, False, True, True, True]).drop_duplicates("strategy")


def candidates(baseline, seed):
    """Fixed one-factor grid plus seeded interactions, evaluated chronologically."""
    grids = dict(atr_period=[7, 14, 21], atr_multiple=[.5, 1, 1.5, 2, 3],
                 fib_tolerance=[.02, .03, .05, .08, .10], entry_mode=[1, 2, 3, 9, 11, 12, 13],
                 stop_mode=[3, 4, 5, 6, 7, 8, 9], target_r=[1, 1.5, 2, 2.5, 3, 4, 5],
                 filter_mode=["none", "ema20", "ema50", "ema100", "ema200", "rsi",
                              "macd", "relative_volume", "high_atr", "low_atr", "utc_asia",
                              "utc_europe", "utc_america"])
    keys = list(grids)
    seen = set()
    rng = np.random.default_rng(seed)
    layouts = [baseline, *({**baseline, key: value} for key, options in grids.items() for value in options),
               *({**baseline, "exit_mode": 14, "management_r": r} for r in (1.5, 2., 3.)),
               *({**baseline, "exit_mode": 17, "management_r": r, "target_r": 3.} for r in (1., 1.5, 2.))]
    choices = [tuple(rng.choice(len(grids[k])) for k in keys) for _ in range(12)]
    layouts.extend({**baseline, **{k: grids[k][ix] for k, ix in zip(keys, indexes)}} for indexes in choices)
    for layout in layouts:
        signature = tuple(layout[k] for k in [*keys, "exit_mode", "management_r"])
        if signature not in seen:
            seen.add(signature)
            yield layout


def choose_variants(frame):
    rows = frame.loc[frame.trades >= 20].copy()
    rows["score"] = rows.sharpe - .015 * rows.drawdown_pct
    # Validate only the three strongest training variants; never rank on the final period.
    training = rows[rows.period == "train"].nlargest(3, "score")
    validation = rows[(rows.period == "validation") & rows.trial.isin(training.trial)]
    if len(validation):
        return int(validation.sort_values(["score", "trial"], ascending=[False, True]).iloc[0].trial)
    return int(training.iloc[0].trial) if len(training) else 0


def distinct_finalists(plans, limit):
    # Some rules deliberately reuse the same signal or partition the same events.
    families = {1: "pullback", 31: "pullback", 2: "breakout", 4: "breakout", 30: "breakout"}
    seen, selected = set(), []
    for key in sorted(plans, key=lambda k: (-plans[k]["rank_score"], k)):
        strategy = plans[key]["strategy"]
        family = families.get(strategy, key)
        if family in seen:
            continue
        seen.add(family)
        selected.append(key)
        if len(selected) == limit:
            break
    return selected


def bot_subsets():
    bots = ("shahin", "mojsavar", "ghoghnous")
    return [tuple(bot for bot, include in zip(bots, flags) if include)
            for flags in product((False, True), repeat=3) if any(flags)]
