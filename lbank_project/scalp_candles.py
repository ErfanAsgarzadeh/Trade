"""Build 15m and 1h quote-sampled futures OHLCV for the optional Chabok sleeve.

Separate from lbank_candles.py: it cannot modify any 4h CSV. The source is
LBank's public perpetual quote marketData endpoint, not spot OHLCV.
No real traded volume; every bar has volume=0. Sampling misses short wicks.
"""
from __future__ import annotations

import json
import logging
import os
import signal
import sys
import time
from pathlib import Path

from lbank_candles import (fetch_prices, lbank_name, read_rows, write_rows)

LOG = logging.getLogger("scalp_candles")
TF = {"15m": 900, "1h": 3600}
SAMPLE = float(os.getenv("SCALP_CANDLE_SAMPLE_SECONDS", "10"))
FLUSH = float(os.getenv("SCALP_CANDLE_WRITE_SECONDS", "60"))
OUT = Path(os.getenv("OHLCV_DIR", "data/ohlcv"))
CONFIG = Path(os.getenv("SCALP_CONFIG", str(Path(__file__).with_name("scalp_config.json"))))


def csv_path(symbol: str, timeframe: str) -> Path:
    if timeframe not in TF:
        raise ValueError("Unsupported timeframe")
    return OUT / (symbol.replace("/", "_").replace(":", "_") + "_" + timeframe + ".csv")


class Collector:
    def __init__(self, symbols: list[str]):
        self.symbols = list(symbols)
        self.open_bars = {}
        self.dirty = set()
        self.last_flush = 0.0
        for symbol in self.symbols:
            for tf in TF:
                rows = read_rows(csv_path(symbol, tf))
                if rows:
                    self.open_bars[(symbol, tf)] = rows[-1]

    def step(self, prices: dict[str, float], now: float):
        for symbol in self.symbols:
            px = prices.get(lbank_name(symbol))
            if not isinstance(px, (int, float)) or px <= 0:
                continue
            for tf, period in TF.items():
                key = (symbol, tf)
                ts = (int(now) // period) * period * 1000
                bar = self.open_bars.get(key)
                if bar is None or bar[0] < ts:
                    if bar is not None:
                        self.flush(key)
                    self.open_bars[key] = [ts, float(px), float(px), float(px), float(px), 0.0]
                elif bar[0] == ts:
                    bar[2] = max(bar[2], float(px))
                    bar[3] = min(bar[3], float(px))
                    bar[4] = float(px)
                else:
                    continue  # clock rollback: reject, never overwrite future bar
                self.dirty.add(key)
        if now - self.last_flush >= FLUSH:
            self.flush_all(now)

    def flush(self, key):
        symbol, tf = key
        path = csv_path(symbol, tf)
        bar = self.open_bars[key]
        rows = read_rows(path)
        if rows and rows[-1][0] == bar[0]:
            rows[-1] = list(bar)
        elif not rows or rows[-1][0] < bar[0]:
            rows.append(list(bar))
        else:
            raise ValueError("Out-of-order candle append")
        write_rows(path, rows)
        self.dirty.discard(key)

    def flush_all(self, now):
        for key in sorted(self.dirty):
            self.flush(key)
        self.last_flush = now


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = json.loads(CONFIG.read_text())
    symbols = cfg["symbols"]
    collector = Collector(symbols)
    stopping = {"value": False}
    signal.signal(signal.SIGTERM, lambda *_: stopping.update(value=True))
    LOG.info("Collecting futures quote-sampled 15m/1h candles for %s", symbols)
    while not stopping["value"]:
        try:
            prices = fetch_prices()
            collector.step(prices, time.time())
        except Exception:
            LOG.exception("Scalp collector fetch failed; preserving historical gaps")
        if argv and "--once" in argv:
            collector.flush_all(time.time())
            return 0
        time.sleep(max(0.5, SAMPLE))
    collector.flush_all(time.time())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
