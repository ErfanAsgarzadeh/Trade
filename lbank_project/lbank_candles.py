"""Build 4h futures candles from LBank's public perpetual quotes (the exchange publishes no futures K-line endpoint).

Every SAMPLE_SECONDS the collector reads GET https://lbkperp.lbank.com/cfd/openApi/v1/pub/marketData?productGroup=SwapU
(one call for every contract) and folds lastPrice into the open 4h bar of each configured symbol. Output, one file per
symbol in OHLCV_DIR (what PAPER_DATA_MODE=csv-lbank expects):  BTC_USDT_USDT_4h.csv  with the header
timestamp,open,high,low,close,volume   (timestamp = bar open, ms, UTC-aligned to 4h). The LAST row is the bar that is still
forming; the bots drop it, exactly as with an exchange K-line feed.

Honest limits: high/low are the extremes of the sampled last prices (wicks shorter than SAMPLE_SECONDS can be missed),
volume is not available per bar and is written as 0, and a period in which the collector was not running stays a gap in the
history (the bots refuse symbols whose recent history has more than max_gap_bars missing bars). History starts the day the
collector first runs: the bots need ~17 days (Shahin), ~34 days (Mojsavar, EMA200) and ~83 days (Ghoghnous volatility rank) of closed bars.

Fast start (history): seed_ohlcv/ ships ~250 days of closed 4h bars (LBank SPOT 4h candles, ONE from Binance spot) so the bots can
start trading after the first collector run instead of after months of warm-up. At start-up and after every outage the collector
fills the missing closed bars from LBank spot candles (CANDLE_BACKFILL=0 turns that off). Spot is an approximation of the perpetual
(small basis; larger on thin alts) and is only used for history, never for live prices.

python lbank_candles.py [--once]       symbols = union of BOT_CONFIG, C3_CONFIG, PA_CONFIG
"""
import csv
import json
import logging
import os
import signal
import sys
import time
import urllib.request
from pathlib import Path

URL = "https://lbkperp.lbank.com/cfd/openApi/v1/pub/marketData?productGroup=SwapU"
H4 = 4 * 3600
HEADER = ["timestamp", "open", "high", "low", "close", "volume"]
SPOT = "https://api.lbkex.com/v2/kline.do?symbol={name}&size={size}&type=hour4&time={start}"
BACKFILL = os.getenv("CANDLE_BACKFILL", "1") != "0"
SEED = Path(os.getenv("SEED_OHLCV_DIR", str(Path(__file__).with_name("seed_ohlcv"))))
SAMPLE_SECONDS = float(os.getenv("CANDLE_SAMPLE_SECONDS", "10"))
WRITE_SECONDS = float(os.getenv("CANDLE_WRITE_SECONDS", "60"))
OUT = Path(os.getenv("OHLCV_DIR", "data/ohlcv"))
LOG = logging.getLogger("candles")


def config_symbols() -> list[str]:
    names = []
    for env, default in (("BOT_CONFIG", "config.json"), ("C3_CONFIG", "c3_config.json"), ("PA_CONFIG", "pa_config.json")):
        path = Path(os.getenv(env, default))
        if not path.is_file():                     # runtime copy not created yet: use the shipped config
            path = Path(__file__).with_name(default)
        if path.is_file():
            names += json.loads(path.read_text())["symbols"]
    return sorted(set(names))


def lbank_name(symbol: str) -> str:
    return symbol.split("/")[0] + "USDT"          # BTC/USDT:USDT -> BTCUSDT


def csv_path(symbol: str) -> Path:
    return OUT / (symbol.replace("/", "_").replace(":", "_") + "_4h.csv")


def fetch_prices() -> dict[str, float]:
    request = urllib.request.Request(URL, headers={"User-Agent": "lbank-paper-bot"})
    with urllib.request.urlopen(request, timeout=10) as response:
        body = json.loads(response.read())
    if not body.get("success") or not isinstance(body.get("data"), list):
        raise ValueError(f"unexpected marketData reply: {str(body)[:200]}")
    out = {}
    for item in body["data"]:
        try:
            price = float(item["lastPrice"])
        except (KeyError, TypeError, ValueError):
            continue
        if price > 0:
            out[item["symbol"]] = price
    return out


def sane(row: list[float]) -> list[float]:
    """Exchange candles occasionally print an open/close outside high/low; widen high/low to contain them."""
    ts, o, h, l, c, v = row
    return [ts, o, max(h, o, c), min(l, o, c), c, v]


def spot_klines(symbol: str, start_ms: int, until_ms: int) -> list[list[float]]:
    """Closed LBank SPOT 4h bars with start_ms <= open < until_ms ([ts_ms,o,h,l,c,v]); [] when the coin has no spot market."""
    size = min(2000, max(2, (until_ms - start_ms) // (H4 * 1000) + 2))
    url = SPOT.format(name=symbol.split("/")[0].lower() + "_usdt", size=size, start=start_ms // 1000)
    request = urllib.request.Request(url, headers={"User-Agent": "lbank-paper-bot"})
    with urllib.request.urlopen(request, timeout=15) as response:
        body = json.loads(response.read())
    out = [[float(r[0]) * 1000, *map(float, r[1:6])] for r in (body.get("data") or [])]
    return [sane(r) for r in out if start_ms <= r[0] < until_ms]


def read_rows(path: Path) -> list[list[float]]:
    if not path.is_file():
        return []
    with path.open(newline="") as fh:
        reader = csv.reader(fh)
        if next(reader, None) != HEADER:
            raise ValueError(f"bad header in {path}")
        return [[float(x) for x in row] for row in reader if row]


def write_rows(path: Path, rows: list[list[float]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(HEADER)
        for row in rows:
            writer.writerow([int(row[0])] + [repr(float(x)) for x in row[1:]])
    os.replace(tmp, path)      # atomic: the bots never read a partial file


class Collector:
    def __init__(self, symbols: list[str]):
        self.symbols = symbols
        self.bars: dict[str, list[float]] = {}     # symbol -> forming bar [ts_ms, o, h, l, c, v]
        self.dirty: set[str] = set()
        self.last_write = 0.0
        for symbol in symbols:                     # resume a bar that was forming before a restart
            self.install_seed(symbol)
            rows = read_rows(csv_path(symbol))
            if rows:
                self.bars[symbol] = rows[-1]

    @staticmethod
    def install_seed(symbol: str) -> None:
        """First run: start from the shipped history instead of an empty file."""
        target, seed = csv_path(symbol), SEED / csv_path(symbol).name
        if not target.is_file() and seed.is_file():
            write_rows(target, read_rows(seed))
            LOG.info("%s: history seeded from %s", symbol, seed.name)

    def backfill(self, symbol: str, bar_ts: int) -> None:
        """Replace/append the closed bars between the last stored bar and the current one with LBank spot candles."""
        if not BACKFILL:
            return
        rows = read_rows(csv_path(symbol))
        if not rows or rows[-1][0] >= bar_ts - H4 * 1000:
            return                                  # nothing missing
        try:
            fresh = spot_klines(symbol, int(rows[-1][0]), bar_ts)
        except Exception as exc:
            LOG.warning("%s: gap since %s could not be filled (%s)", symbol, int(rows[-1][0]), exc)
            return
        if fresh:
            write_rows(csv_path(symbol), [r for r in rows if r[0] < fresh[0][0]] + fresh)
            LOG.info("%s: filled %d missing 4h bars from spot", symbol, len(fresh))

    def step(self, prices: dict[str, float], now: float) -> None:
        bar_ts = int(now) // H4 * H4 * 1000
        for symbol in self.symbols:
            price = prices.get(lbank_name(symbol))
            if price is None:
                continue
            bar = self.bars.get(symbol)
            if bar is None or bar[0] < bar_ts:
                if bar is not None:
                    self.flush(symbol)             # persist the final values of the bar that just closed
                self.backfill(symbol, bar_ts)
                self.bars[symbol] = [bar_ts, price, price, price, price, 0.0]
                self.dirty.add(symbol)
                self.flush(symbol, new_bar=True)
            elif bar[0] == bar_ts:
                bar[2] = max(bar[2], price)
                bar[3] = min(bar[3], price)
                bar[4] = price
                self.dirty.add(symbol)
        if now - self.last_write >= WRITE_SECONDS:
            self.flush_all(now)

    def flush(self, symbol: str, new_bar: bool = False) -> None:
        path = csv_path(symbol)
        rows = read_rows(path)
        bar = self.bars[symbol]
        if rows and rows[-1][0] == bar[0]:
            rows[-1] = bar
        elif rows and not new_bar:
            rows = [r for r in rows if r[0] < bar[0]] + [bar]
        else:
            rows.append(bar)
        write_rows(path, rows)
        self.dirty.discard(symbol)

    def flush_all(self, now: float) -> None:
        for symbol in sorted(self.dirty):
            self.flush(symbol)
        self.last_write = now


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    symbols = config_symbols()
    if not symbols:
        sys.exit("no symbols: set BOT_CONFIG / C3_CONFIG / PA_CONFIG")
    collector = Collector(symbols)
    stop = {"now": False}
    signal.signal(signal.SIGTERM, lambda *_: stop.update(now=True))
    LOG.info("collecting 4h candles for %d symbols into %s", len(symbols), OUT)
    failures = 0
    while not stop["now"]:
        started = time.time()
        try:
            prices = fetch_prices()
            missing = [s for s in symbols if lbank_name(s) not in prices]
            if missing and failures == 0:
                LOG.warning("no quote for %s", missing)
            collector.step(prices, time.time())
            failures = 0
        except Exception as exc:                   # network/API errors: keep going, the gap rules protect the bots
            failures += 1
            if failures in (1, 10) or failures % 100 == 0:
                LOG.error("marketData failed (%d in a row): %s", failures, exc)
        if "--once" in argv:
            collector.flush_all(time.time() + WRITE_SECONDS)
            return 0
        time.sleep(max(0.5, SAMPLE_SECONDS - (time.time() - started)))
    collector.flush_all(time.time() + WRITE_SECONDS)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
