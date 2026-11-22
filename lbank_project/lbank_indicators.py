"""Candle validation, indicators, and entry signals for the LBank strategy."""

import math

import numpy as np
import pandas as pd

import strategy_archetypes as archetypes


TIMEFRAMES = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800,
              "1h": 3600, "4h": 14400, "1d": 86400}


def wilder(values: pd.Series, period: int) -> pd.Series:
    """Seed with the first period's SMA; then use Wilder's recursive smoothing."""
    result = np.full(len(values), np.nan)
    raw = values.to_numpy(dtype=float)
    start = next((i for i in range(len(raw)) if np.isfinite(raw[i])), len(raw))
    seed = start + period - 1
    if seed < len(raw) and np.isfinite(raw[start:seed + 1]).all():
        result[seed] = float(raw[start:seed + 1].mean())
        for index in range(seed + 1, len(raw)):
            if not np.isfinite(raw[index]):
                break
            result[index] = (result[index - 1] * (period - 1) + raw[index]) / period
    return pd.Series(result, index=values.index)


def adx_wilder(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Wilder ADX with the period-1 DM/TR seed and mean of first period DX."""
    output = np.full(len(df), np.nan)
    high, low, close = (df[field].to_numpy(dtype=float) for field in ("high", "low", "close"))
    plus = minus = true_range = dx_sum = adx = 0.0
    count = 0
    for index in range(1, len(df)):
        up, down = high[index] - high[index - 1], low[index - 1] - low[index]
        pdm = up if up > down and up > 0 else 0.0
        mdm = down if down > up and down > 0 else 0.0
        tr = max(high[index] - low[index], abs(high[index] - close[index - 1]), abs(low[index] - close[index - 1]))
        if index < period:
            plus += pdm
            minus += mdm
            true_range += tr
            continue
        plus = plus - plus / period + pdm
        minus = minus - minus / period + mdm
        true_range = true_range - true_range / period + tr
        dx = 100 * abs(plus - minus) / (plus + minus) if plus + minus > 0 else 0.0
        if count < period:
            dx_sum += dx
            count += 1
            if count == period:
                adx = dx_sum / period
                output[index] = adx
        else:
            adx = (adx * (period - 1) + dx) / period
            output[index] = adx
    return pd.Series(output, index=df.index)


def closed_rows(bars):
    # Official history is explicitly closed-only; legacy feeds include a forming final bar.
    return bars if getattr(bars, 'closed_only', False) else bars[:-1]


def true_range(candles: pd.DataFrame) -> pd.Series:
    """Return each candle's true range, using its high-low range for the first row."""
    previous_close = candles.close.shift(1)
    return pd.concat([
        candles.high - candles.low,
        (candles.high - previous_close).abs(),
        (candles.low - previous_close).abs(),
    ], axis=1).max(axis=1)


def indicators(bars: list, c: dict, timeframe: str, now: float) -> pd.DataFrame:
    df = pd.DataFrame(closed_rows(bars), columns=["timestamp", "open", "high", "low", "close", "volume"])
    if df.empty:
        raise ValueError("Empty OHLCV response")
    df = df.astype(float)
    if not np.isfinite(df.to_numpy()).all() or not df.timestamp.is_monotonic_increasing or df.timestamp.duplicated().any():
        raise ValueError("Non-finite, duplicate or unsorted candles")
    if ((df.high < df[["open", "close", "low"]].max(axis=1)) |
        (df.low > df[["open", "close", "high"]].min(axis=1)) |
        (df[["open", "high", "low", "close"]].min(axis=1) <= 0) |
        (df.volume < 0)).any():
        raise ValueError("Invalid OHLCV geometry")
    # closed_rows discards forming bars unless the source is explicitly closed-only.
    seconds = TIMEFRAMES[timeframe]
    df = df[df.timestamp + seconds * 1000 <= now * 1000].reset_index(drop=True)
    if len(df) and (np.diff(df.timestamp) != seconds * 1000).any():
        raise ValueError("Gaps in candle history")
    i, f = c["ichimoku_params"], c["filters_and_triggers"]
    for name, period in (("tenkan", i["tenkan"]), ("kijun", i["kijun"]), ("senkou_b_future", i["senkou_b"])):
        df[name] = (df.high.rolling(period).max() + df.low.rolling(period).min()) / 2
    df["senkou_a_future"] = (df.tenkan + df.kijun) / 2
    df["senkou_a_curr"] = df.senkou_a_future.shift(i["displacement"])
    df["senkou_b_curr"] = df.senkou_b_future.shift(i["displacement"])
    df["kumo_top"] = df[["senkou_a_curr", "senkou_b_curr"]].max(axis=1, skipna=False)
    df["kumo_bottom"] = df[["senkou_a_curr", "senkou_b_curr"]].min(axis=1, skipna=False)
    delta = df.close.diff()
    gain = wilder(delta.clip(lower=0), f["rsi_period"])
    loss = wilder(-delta.clip(upper=0), f["rsi_period"])
    df["rsi"] = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
    df.loc[(loss == 0) & (gain > 0), "rsi"] = 100.0
    df.loc[(gain == 0) & (loss > 0), "rsi"] = 0.0
    df.loc[(gain == 0) & (loss == 0), "rsi"] = 50.0
    df["atr"] = wilder(true_range(df), f["atr_period"])
    df["adx"] = adx_wilder(df, c.get("structural_filters", {}).get("adx_period", 14))
    return archetypes.add_features(df) if c.get("archetype_strategy", archetypes.DEFAULTS)["family"] != "LEGACY" else df


def atr_regime_ratio(bars: list, c: dict, timeframe: str, now: float, window: int) -> float | None:
    """ATR of the last closed bar / median ATR of the `window` closed bars before it.

    Every ATR is the value indicators() would report as the last row of its own runtime window
    (candle_fetch_limit fetched, forming bar dropped), exactly like the research features, so `bars`
    must hold candle_fetch_limit + window candles. None when history is short, gapped or not finite.
    """
    df = pd.DataFrame(closed_rows(bars), columns=["timestamp", "open", "high", "low", "close", "volume"]).astype(float)
    seconds = TIMEFRAMES[timeframe]
    df = df[df.timestamp + seconds * 1000 <= now * 1000].reset_index(drop=True)
    span = c["ichimoku_params"]["candle_fetch_limit"] - 1
    if len(df) < span + window or (np.diff(df.timestamp.to_numpy()[-(span + window):]) != seconds * 1000).any():
        return None
    period = c["filters_and_triggers"]["atr_period"]
    values = []
    for end in range(len(df) - window - 1, len(df)):
        candles = df.iloc[end - span + 1:end + 1]
        atr = wilder(true_range(candles).reset_index(drop=True), period)
        values.append(float(atr.iloc[-1]))
    current, median = values[-1], float(np.median(values[:-1]))
    if not (math.isfinite(current) and math.isfinite(median) and median > 0):
        return None
    return current / median


def late_entry_move(df: pd.DataFrame, side: str, bars: int) -> float | None:
    """Side-signed log move of the last closed close versus the close `bars` candles earlier (None if too short)."""
    if len(df) <= bars:
        return None
    now, then = float(df.close.iloc[-1]), float(df.close.iloc[-1 - bars])
    if not (math.isfinite(now) and math.isfinite(then) and now > 0 and then > 0):
        return None
    return (1 if side == "long" else -1) * math.log(now / then)


def regime(df: pd.DataFrame, c: dict) -> str | None:
    if c.get("archetype_strategy", archetypes.DEFAULTS)["family"] != "LEGACY":
        if df.empty:
            return None
        longs, shorts = archetypes.regime_masks(df, c)
        return "long" if longs.iloc[-1] else "short" if shorts.iloc[-1] else None
    displacement = c["ichimoku_params"]["displacement"]
    if len(df) <= displacement:
        return None
    bar, prior = df.iloc[-1], df.iloc[-1 - displacement]
    fields = ["close", "tenkan", "kijun", "senkou_a_future", "senkou_b_future", "kumo_top", "kumo_bottom", "atr"]
    if not np.isfinite(bar[fields]).all() or not np.isfinite(prior[["high", "low", "kumo_top", "kumo_bottom"]]).all() or bar.atr <= 0:
        return None
    if bar.kumo_bottom <= bar.close <= bar.kumo_top or abs(bar.senkou_a_future - bar.senkou_b_future) < 0.15 * bar.atr:
        return None
    structural = c.get("structural_filters", {})
    threshold = structural.get("min_htf_adx", 0)
    if threshold and ("adx" not in df or not math.isfinite(bar.adx) or bar.adx < threshold):
        return None
    long_slope = short_slope = True
    if structural.get("enable_htf_slope_filter", False):
        if len(df) < 4:
            return None
        long_slope = bar.kijun >= df.iloc[-4].kijun and bar.tenkan > df.iloc[-3].tenkan
        short_slope = bar.kijun <= df.iloc[-4].kijun and bar.tenkan < df.iloc[-3].tenkan
    if (bar.close > bar.kumo_top and bar.tenkan >= bar.kijun and
            bar.senkou_a_future > bar.senkou_b_future and
            bar.close > prior.high and bar.close > prior.kumo_top and long_slope):
        return "long"
    if (bar.close < bar.kumo_bottom and bar.tenkan <= bar.kijun and
            bar.senkou_a_future < bar.senkou_b_future and
            bar.close < prior.low and bar.close < prior.kumo_bottom and short_slope):
        return "short"
    return None


def entry_signal(df: pd.DataFrame, side: str, c: dict, htf: pd.DataFrame | None = None) -> bool:
    if c.get("archetype_strategy", archetypes.DEFAULTS)["family"] != "LEGACY":
        source = htf if c["archetype_strategy"]["family"] == "DONCHIAN" and htf is not None else df
        if source.empty or side not in ("long", "short"):
            return False
        longs, shorts = archetypes.entry_masks(source, c)
        return bool((longs if side == "long" else shorts).iloc[-1])
    f, a = c["filters_and_triggers"], c["al_brooks_filters"]
    t = len(df) - 1
    if side not in ("long", "short") or t < max(a["barb_wire_lookback"], a["h2_l2_lookback_bars"] + 1):
        return False
    b = df.iloc[t]
    if not np.isfinite(b[["kijun", "rsi", "atr"]]).all() or b.atr <= 0:
        return False
    if abs(b.close - b.kijun) > f["max_kijun_extension_atr"] * b.atr:
        return False
    if side == "long":
        touch = b.low <= b.kijun + f["kijun_touch_atr_tolerance"] * b.atr and b.close > b.kijun
    else:
        touch = b.high >= b.kijun - f["kijun_touch_atr_tolerance"] * b.atr and b.close < b.kijun
    if not touch or not f[f"{side}_rsi_min"] <= b.rsi <= f[f"{side}_rsi_max"]:
        return False
    if a["enable_barb_wire_filter"]:
        tail = df.iloc[t - a["barb_wire_lookback"] + 1:t + 1]
        doji = any(abs(row.close - row.open) <= a["barb_wire_doji_body_ratio"] * max(row.high - row.low, 1e-8)
                   for row in tail.itertuples())
        overlaps = []
        for index in range(1, len(tail)):
            x, y = tail.iloc[index], tail.iloc[index - 1]
            overlaps.append(max(0.0, min(x.high, y.high) - max(x.low, y.low)) / max(x.high - x.low, 1e-8))
        if doji and all(v >= a["barb_wire_min_overlap_ratio"] for v in overlaps):
            return False
    if a["require_h2_l2_pullback"]:
        found = False
        for k in range(max(1, t - a["h2_l2_lookback_bars"]), t - 1):
            x, previous = df.iloc[k], df.iloc[k - 1]
            leg1 = x.high > previous.high if side == "long" else x.low < previous.low
            leg2 = any((df.iloc[m].low < x.low if side == "long" else df.iloc[m].high > x.high)
                       for m in range(k + 1, t + 1))
            found = found or (leg1 and leg2)
        if not found:
            return False
    body, span = abs(b.close - b.open), max(b.high - b.low, 1e-8)
    lower, upper = min(b.open, b.close) - b.low, b.high - max(b.open, b.close)
    if side == "long":
        return bool((b.close - b.low) / span >= 0.60 and
                    (lower >= 1.2 * body or (b.close > b.open and body >= 0.50 * span)))
    return bool((b.high - b.close) / span >= 0.60 and
                (upper >= 1.2 * body or (b.close < b.open and body >= 0.50 * span)))
