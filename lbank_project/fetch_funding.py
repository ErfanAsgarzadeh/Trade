"""Maintain FUNDING_DIR/<symbol>_funding.csv (timestamp,funding_rate) for every configured symbol.

Sources (python fetch_funding.py [config.json] [--source lbank|binance]):
  lbank   (default) LBank has no funding-history endpoint, so each run records the CURRENT rate under its next
          settlement timestamp and keeps the latest observation per settlement. Run it at least hourly (cron); after
          3 days (9 settlements) the bot has enough history. Until then the bot does not block anything.
  binance Binance USDT-M public history (the data the F4 research used); unreachable from some regions (HTTP 451).
Files are replaced atomically so the bot never reads a partial file.
"""
import json
import os
import sys
import urllib.request
from pathlib import Path

import ccxt

URL = "https://fapi.binance.com/fapi/v1/fundingRate?symbol={symbol}&limit=100"


def binance_symbol(symbol: str) -> str:
    return symbol.split(":")[0].replace("/", "")


def rows_from(payload: list) -> list[tuple[int, float]]:
    return sorted((int(x["fundingTime"]), float(x["fundingRate"])) for x in payload)


def read_csv(path: Path) -> dict[int, float]:
    if not path.is_file():
        return {}
    lines = path.read_text().splitlines()[1:]
    return {int(t): float(r) for t, r in (line.split(",") for line in lines if line)}


def write_csv(path: Path, rows: list[tuple[int, float]]) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text("timestamp,funding_rate\n" + "".join(f"{t},{r!r}\n" for t, r in sorted(rows)))
    tmp.replace(path)


def merge_lbank(path: Path, info: dict, keep: int = 200) -> list[tuple[int, float]]:
    rows = read_csv(path)
    rows[int(info["fundingTimestamp"])] = float(info["fundingRate"])   # latest observation before settlement wins
    return sorted(rows.items())[-keep:]


def main(*args: str) -> int:
    source = "binance" if "--source" in args and args[args.index("--source") + 1] == "binance" else "lbank"
    config_path = next((a for a in args if a.endswith(".json")), "config.json")
    out = Path(os.getenv("FUNDING_DIR", "data/funding"))
    out.mkdir(parents=True, exist_ok=True)
    exchange = ccxt.lbank({"enableRateLimit": True, "timeout": 10000, "options": {"defaultType": "swap"}}) if source == "lbank" else None
    failed = 0
    for symbol in json.loads(Path(config_path).read_text())["symbols"]:
        path = out / (symbol.replace("/", "_").replace(":", "_") + "_funding.csv")
        try:
            if source == "lbank":
                rows = merge_lbank(path, exchange.fetch_funding_rate(symbol))
            else:
                with urllib.request.urlopen(URL.format(symbol=binance_symbol(symbol)), timeout=20) as response:
                    rows = rows_from(json.load(response))
            write_csv(path, rows)
            print(symbol, len(rows), "prints")
        except Exception as exc:  # keep the previous file; the bot treats stale data as "no filter"
            failed += 1
            print(symbol, "FAILED", exc, file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
