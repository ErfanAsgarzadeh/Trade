"""Write seed_ohlcv/<symbol>_4h.csv: ~250 days of CLOSED 4h bars so a fresh install can trade soon.

Source: LBank SPOT 4h candles (same exchange, same UTC 4h grid as the live collector). Coins without an LBank spot market
(ONE) use Binance spot. This is history only; the collector keeps the files current from LBank perpetual quotes.
Run on a machine that can reach the exchanges:  python seed_history.py [bars=1500]
"""
import json
import sys
import time
import urllib.request
from pathlib import Path

import lbank_candles as L

BINANCE = "https://data-api.binance.vision/api/v3/klines?symbol={name}USDT&interval=4h&limit=1000&endTime={end}"


def binance_klines(symbol: str, until_ms: int, bars: int) -> list[list[float]]:
    out, end = [], until_ms - 1
    while len(out) < bars:
        request = urllib.request.Request(BINANCE.format(name=symbol.split("/")[0], end=end), headers={"User-Agent": "lbank-paper-bot"})
        with urllib.request.urlopen(request, timeout=15) as response:
            chunk = json.loads(response.read())
        if not chunk:
            break
        out = [L.sane([float(r[0]), *map(float, r[1:6])]) for r in chunk] + out
        end = int(chunk[0][0]) - 1
    return out[-bars:]


def main(bars: int = 1500) -> None:
    now_ms = int(time.time()) // L.H4 * L.H4 * 1000          # open of the bar still forming: excluded
    L.SEED.mkdir(parents=True, exist_ok=True)
    for symbol in L.config_symbols():
        start = now_ms - bars * L.H4 * 1000
        try:
            rows, source = L.spot_klines(symbol, start, now_ms), "lbank-spot"
        except Exception as exc:
            rows, source = [], f"lbank-spot failed: {exc}"
        if len(rows) < bars * 0.9:
            rows, source = binance_klines(symbol, now_ms, bars), "binance-spot"
        steps = [b[0] - a[0] for a, b in zip(rows, rows[1:])]
        gaps = sum(1 for d in steps if d != L.H4 * 1000)
        L.write_rows(L.SEED / L.csv_path(symbol).name, rows)
        print(f"{symbol:16s} {len(rows):5d} bars  {source:12s} gaps={gaps}", flush=True)
        time.sleep(0.2)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 1500)
