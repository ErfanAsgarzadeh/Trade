"""Instrument specs for the multi-asset FX lab (all-in cost assumptions, documented).

spread / slip are in price units (bid -> ask distance, adverse slippage per fill).
comm is commission per side as a fraction of notional ($7 per 100k round trip = 3.5e-5).
pip is the unit used for the minimum stop distance (min_stop_pips * pip).
Swap: long pays/earns (rate[base] - rate[quote] - markup) per year on notional; for metals
and indices the "base" carry is the lease rate / dividend yield (approximation).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import shahin_fx as sfx

FX_COMM = 7.0 / 200_000
SPEC = {
    # symbol:   pip,    spread,  slip,   comm
    "EURUSD": (1e-4, 0.6e-4, 0.2e-4, FX_COMM),
    "GBPUSD": (1e-4, 0.9e-4, 0.2e-4, FX_COMM),
    "USDJPY": (1e-2, 0.8e-2, 0.2e-2, FX_COMM),
    "AUDUSD": (1e-4, 0.8e-4, 0.2e-4, FX_COMM),
    "USDCAD": (1e-4, 1.0e-4, 0.2e-4, FX_COMM),
    "USDCHF": (1e-4, 1.0e-4, 0.2e-4, FX_COMM),
    "NZDUSD": (1e-4, 1.2e-4, 0.2e-4, FX_COMM),
    "EURJPY": (1e-2, 1.2e-2, 0.3e-2, FX_COMM),
    "GBPJPY": (1e-2, 1.8e-2, 0.4e-2, FX_COMM),
    "EURGBP": (1e-4, 1.0e-4, 0.2e-4, FX_COMM),
    "AUDJPY": (1e-2, 1.3e-2, 0.3e-2, FX_COMM),
    "XAUUSD": (0.1, 0.25, 0.05, FX_COMM),     # gold: 25 cents all-in spread
    "XAGUSD": (0.01, 0.025, 0.005, FX_COMM),  # silver
    "SPXUSD": (1.0, 0.6, 0.25, 0.0),          # S&P 500 CFD, spread only
    "NSXUSD": (2.0, 1.5, 0.75, 0.0),          # Nasdaq 100 CFD, spread only
}

RATES = dict(sfx.POLICY_RATES)
RATES.update({
    "AUD": [("2021-01-01", 0.10), ("2022-05-04", 0.35), ("2022-06-08", 0.85), ("2022-07-06", 1.35),
            ("2022-08-03", 1.85), ("2022-09-07", 2.35), ("2022-10-05", 2.60), ("2022-11-02", 2.85),
            ("2022-12-07", 3.10), ("2023-02-08", 3.35), ("2023-03-08", 3.60), ("2023-05-03", 3.85),
            ("2023-06-07", 4.10), ("2023-11-08", 4.35), ("2025-02-19", 4.10), ("2025-05-21", 3.85),
            ("2025-08-13", 3.60)],
    "CAD": [("2021-01-01", 0.25), ("2022-03-03", 0.50), ("2022-04-14", 1.00), ("2022-06-02", 1.50),
            ("2022-07-14", 2.50), ("2022-09-08", 3.25), ("2022-10-27", 3.75), ("2022-12-08", 4.25),
            ("2023-01-26", 4.50), ("2023-06-08", 4.75), ("2024-06-06", 4.50), ("2024-07-25", 4.25),
            ("2024-09-05", 4.00), ("2024-10-24", 3.75), ("2024-12-12", 3.25), ("2025-01-30", 3.00),
            ("2025-03-13", 2.75), ("2025-09-18", 2.50), ("2025-10-30", 2.25)],
    "CHF": [("2021-01-01", -0.75), ("2022-06-17", -0.25), ("2022-09-23", 0.50), ("2022-12-16", 1.00),
            ("2023-03-24", 1.50), ("2023-06-23", 1.75), ("2024-03-22", 1.50), ("2024-06-21", 1.25),
            ("2024-09-27", 1.00), ("2024-12-13", 0.50), ("2025-03-21", 0.25), ("2025-06-20", 0.00)],
    "NZD": [("2021-01-01", 0.25), ("2021-10-07", 0.50), ("2021-11-25", 0.75), ("2022-02-24", 1.00),
            ("2022-04-14", 1.50), ("2022-05-26", 2.00), ("2022-07-14", 2.50), ("2022-08-18", 3.00),
            ("2022-10-06", 3.50), ("2022-11-24", 4.25), ("2023-02-23", 4.75), ("2023-04-06", 5.25),
            ("2023-05-25", 5.50), ("2024-08-15", 5.25), ("2024-10-10", 4.75), ("2024-11-28", 4.25),
            ("2025-02-20", 3.75), ("2025-04-10", 3.50), ("2025-05-29", 3.25), ("2025-08-21", 3.00),
            ("2025-10-09", 2.50), ("2025-11-27", 2.25)],
    "XAU": [("2021-01-01", 0.0)],   # gold lease rate ~0
    "XAG": [("2021-01-01", 0.0)],
    "SPX": [("2021-01-01", 1.4)],   # approx. dividend yield
    "NSX": [("2021-01-01", 0.7)],
})


def swap_tables(symbols, t_min_ms, t_max_ms, markup_pct=0.5):
    d0 = int(t_min_ms // sfx.DAY_MS) - 1
    d1 = int(t_max_ms // sfx.DAY_MS) + 2
    dates = pd.to_datetime(np.arange(d0, d1) * sfx.DAY_MS, unit="ms").values

    def series(ccy):
        tab = RATES[ccy]
        when = pd.to_datetime([d for d, _ in tab]).values
        idx = np.searchsorted(when, dates, side="right") - 1
        return np.array([tab[max(i, 0)][1] for i in idx])

    long_, short = {}, {}
    for s in symbols:
        diff = series(s[:3]) - series(s[3:])
        long_[s] = (diff - markup_pct) / 100
        short[s] = (-diff - markup_pct) / 100
    return d0, long_, short
