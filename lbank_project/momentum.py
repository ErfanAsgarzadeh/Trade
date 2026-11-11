"""Momentum-rank sizing for the three bots (research: high_cagr/output/ideas/scorer/report_fa.md, momentum_full.json).

New-entry risk is multiplied by 0.5 + r, where r is the coin's percentile rank of its 30-day return among the union of the
three bots' symbols (35 coins by default); for shorts r is replaced by 1 - r. So the multiplier is between ~0.5 and 1.5:
the strongest coins get up to x1.5 for longs, the weakest up to x1.5 for shorts. The 30-day return is measured between the
4h closes at the two UTC midnights 30 days apart, the last one being the most recent completed UTC day (exactly the daily
closes of the research). Ranks are computed once per UTC day and cached.

Safe fallback: when the coin itself or fewer than MIN_COINS coins have both closes, the multiplier is 1.0 (no change).
Open positions are never resized; pyramid adds keep their own existing rule.
"""
from __future__ import annotations
import json, logging, math, os, threading
from pathlib import Path

LOG = logging.getLogger("momentum")
H4 = 4 * 3600
LOOKBACK_DAYS = 30
MIN_COINS = 10
RETRY_S = 900                       # after an insufficient rank set, try again at most every 15 minutes
FETCH = 6 * LOOKBACK_DAYS + 12      # 4h candles needed to reach the close 30 days back, with margin
_lock = threading.Lock()
_cache: dict = {}


def universe() -> list[str]:
    """Union of the symbols of the three bots' configs (the paths the bots use)."""
    here = Path(__file__).resolve().parent
    out: list[str] = []
    for env, name in (("BOT_CONFIG", "config.json"), ("C3_CONFIG", "c3_config.json"), ("PA_CONFIG", "pa_config.json")):
        path = Path(os.getenv(env, str(here / name)))
        if not path.is_file():
            path = here / name          # runtime copy not created yet: the bots seed it from the shipped file
        try:
            data = json.loads(path.read_text())
            for s in data.get("symbols", []):
                if isinstance(s, str) and s not in out:
                    out.append(s)
        except Exception as exc:
            LOG.warning("momentum universe: %s unreadable (%s)", env, type(exc).__name__)
    return out


def _close_at(rows: list, boundary_s: int) -> float | None:
    """Close of the 4h candle that ENDS at boundary_s (timestamps in ms, open time)."""
    want = (boundary_s - H4) * 1000
    for r in reversed(rows):
        if int(r[0]) == want:
            v = float(r[4])
            return v if math.isfinite(v) and v > 0 else None
        if int(r[0]) < want:
            break
    return None


def ranks(data, now: float, symbols: list[str] | None = None) -> dict[str, float]:
    """Percentile rank (ties averaged, like pandas rank(pct=True)) of the 30-day return, for every symbol with data."""
    day_end = int(now) // 86400 * 86400            # the last completed UTC midnight
    start = day_end - LOOKBACK_DAYS * 86400
    rets = {}
    for s in symbols if symbols is not None else universe():
        try:
            rows = data.candles(s, "4h", FETCH)
            a, b = _close_at(rows, start), _close_at(rows, day_end)
            if a and b:
                rets[s] = b / a - 1
        except Exception as exc:
            LOG.debug("momentum: no candles for %s (%s)", s, exc)
    order = sorted(rets.values())
    n = len(order)
    out = {}
    for s, v in rets.items():
        below = sum(1 for x in order if x < v)
        equal = sum(1 for x in order if x == v)
        out[s] = (below + (equal + 1) / 2) / n
    return out


def multiplier(data, symbol: str, side: str, now: float, enabled: bool = True) -> float:
    """Risk multiplier for a NEW entry; 1.0 when disabled or when the rank is unavailable."""
    if not enabled:
        return 1.0
    day = int(now) // 86400
    with _lock:
        hit = _cache.get(day)
        if hit is None or (len(hit[1]) < MIN_COINS and now - hit[0] >= RETRY_S):
            r = ranks(data, now)
            _cache.clear();_cache[day] = (now, r)
            if len(r) >= MIN_COINS:
                LOG.info("momentum ranks for UTC day %s: %d coins", day, len(r))
            else:
                LOG.warning("momentum: only %d coins with 30-day history; sizing unchanged", len(r))
        else:
            r = hit[1]
    if len(r) < MIN_COINS or symbol not in r:
        return 1.0
    v = r[symbol]
    return 0.5 + (v if side == "long" else 1.0 - v)
