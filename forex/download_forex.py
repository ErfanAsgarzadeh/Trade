#!/usr/bin/env python3
"""Download five years of Dukascopy 1m FX candles and derive UTC 1h/4h bars.

No artificial candles are inserted for weekends, holidays or missing minutes.
Uses dukascopy-node CLI, pinned for reproducibility. Python stdlib only.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import subprocess
import sys
from contextlib import ExitStack
from datetime import date, datetime, timezone
from pathlib import Path

START = date(2021, 11, 12)
END = date(2026, 11, 12)  # exclusive: five calendar years
INSTRUMENTS = ("EURUSD", "GBPUSD", "USDJPY")
HEADERS = ("timestamp", "open", "high", "low", "close", "volume")
MINUTE_MS = 60_000
TOOL_VERSION = "1.51.1"
TF_MS = {"1m": MINUTE_MS, "1h": 60 * MINUTE_MS, "4h": 240 * MINUTE_MS}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def milliseconds(day: date) -> int:
    return int(datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp() * 1000)


def months(start: date, end: date):
    cursor = start
    while cursor < end:
        year, month = cursor.year, cursor.month
        next_month = date(year + (month == 12), month % 12 + 1, 1)
        bound = min(next_month, end)
        yield cursor, bound
        cursor = bound


def candles(path: Path, start: date, end: date):
    low, high = milliseconds(start), milliseconds(end)
    previous = None
    with path.open("r", newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != list(HEADERS):
            raise ValueError(f"Unexpected CSV header in {path}: {reader.fieldnames}")
        for line, row in enumerate(reader, start=2):
            try:
                ts = int(row["timestamp"])
                prices = tuple(float(row[k]) for k in HEADERS[1:])
                o, h, l, c, v = prices
                if not (low <= ts < high and ts % MINUTE_MS == 0):
                    raise ValueError("out of range or not UTC-minute aligned")
                if previous is not None and ts <= previous:
                    raise ValueError("duplicate/unsorted minute")
                if not all(math.isfinite(n) for n in prices) or min(o, h, l, c) <= 0 or v < 0:
                    raise ValueError("non-finite or negative prices/volume")
                if h < max(o, l, c) or l > min(o, h, c):
                    raise ValueError("invalid OHLC ordering")
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"{path}:{line}: {exc}") from exc
            previous = ts
            yield (ts, *prices)


def inspect(path: Path, start: date, end: date) -> dict:
    count, first, last = 0, None, None
    for row in candles(path, start, end):
        count += 1
        first = row[0] if first is None else first
        last = row[0]
    if count == 0:
        raise ValueError(f"Empty historical month: {path}")
    return {"file": path.name, "rows": count, "first_ms": first, "last_ms": last, "sha256": sha256(path)}


def fetch_month(pair: str, side: str, begin: date, end: date, root: Path) -> tuple[Path, dict]:
    directory = root / "source" / pair / side
    directory.mkdir(parents=True, exist_ok=True)
    stem = f"{pair.lower()}-{side}-1m-{begin.isoformat()}-{end.isoformat()}"
    target = directory / f"{stem}.csv"
    if target.is_file():
        try:
            return target, inspect(target, begin, end)
        except ValueError as exc:
            print(f"Re-downloading invalid cache ({exc})", file=sys.stderr)
    temporary = directory / f"{stem}.partial.csv"
    temporary.unlink(missing_ok=True)
    command = [
        "npx", "--yes", f"dukascopy-node@{TOOL_VERSION}",
        "-i", pair.lower(), "-from", begin.isoformat(), "-to", end.isoformat(),
        "-t", "m1", "-p", side, "-f", "csv", "-v", "-vu", "units",
        "-dir", str(directory), "-fn", temporary.stem,
        "--cache", "--cache-path", str(root / ".dukascopy-cache"),
        "--retries", "3", "--batch-pause", "1000",
    ]
    print(f"FETCH {pair} {side} [{begin}, {end})", flush=True)
    subprocess.run(command, check=True)
    if not temporary.is_file():
        raise FileNotFoundError(f"Downloader did not write {temporary}")
    details = inspect(temporary, begin, end)
    temporary.replace(target)
    details["file"] = target.name
    return target, details


class Aggregator:
    def __init__(self, interval_ms: int, writer):
        self.interval_ms, self.writer = interval_ms, writer
        self.pending = None
        self.rows = 0
        self.first = self.last = None
        self.partial_buckets = 0

    def push(self, item):
        ts, o, h, l, c, v = item
        key = ts // self.interval_ms * self.interval_ms
        if self.pending is not None and key != self.pending[0]:
            self.flush()
        if self.pending is None:
            self.pending = [key, o, h, l, c, v, 1]
        else:
            p = self.pending
            p[2], p[3], p[4], p[5], p[6] = max(p[2], h), min(p[3], l), c, p[5] + v, p[6] + 1

    def flush(self):
        if self.pending is None:
            return
        p = self.pending
        self.writer.writerow(p[:6])
        self.rows += 1
        self.first = p[0] if self.first is None else self.first
        self.last = p[0]
        if p[6] != self.interval_ms // MINUTE_MS:
            self.partial_buckets += 1
        self.pending = None


def produce(pair: str, side: str, source_files: list[tuple[Path, tuple[date, date]]], start: date, end: date, root: Path) -> dict:
    out = root / "ohlcv"
    out.mkdir(parents=True, exist_ok=True)
    prefix = f"{pair[:3]}_{pair[3:]}_{side}"
    final = {tf: out / f"{prefix}_{tf}.csv" for tf in TF_MS}
    tmp = {tf: path.with_suffix(".csv.tmp") for tf, path in final.items()}
    previous, gap_count, count = None, 0, 0
    try:
        with ExitStack() as stack:
            writers = {}
            for tf in TF_MS:
                stream = stack.enter_context(tmp[tf].open("w", newline="", encoding="utf-8"))
                writer = csv.writer(stream)
                writer.writerow(HEADERS)
                writers[tf] = writer
            aggregates = {tf: Aggregator(TF_MS[tf], writers[tf]) for tf in ("1h", "4h")}
            first = last = None
            for path, (begin, bound) in source_files:
                for item in candles(path, begin, bound):
                    ts = item[0]
                    if previous is not None:
                        if ts <= previous:
                            raise ValueError("Overlapping or unordered monthly files")
                        if ts - previous > MINUTE_MS:
                            gap_count += 1  # includes normal weekends and holidays
                    writers["1m"].writerow(item)
                    for agg in aggregates.values():
                        agg.push(item)
                    count += 1
                    first = ts if first is None else first
                    last, previous = ts, ts
            for agg in aggregates.values():
                agg.flush()
        if not count:
            raise ValueError(f"No candles were downloaded for {pair}")
        for tf, target in final.items():
            tmp[tf].replace(target)
        return {
            "1m": {"file": final["1m"].relative_to(root).as_posix(), "rows": count, "first_ms": first, "last_ms": last,
                   "non_consecutive_intervals": gap_count, "sha256": sha256(final["1m"])},
            **{tf: {"file": final[tf].relative_to(root).as_posix(), "rows": agg.rows,
                    "first_ms": agg.first, "last_ms": agg.last,
                    "partial_buckets": agg.partial_buckets, "sha256": sha256(final[tf])}
               for tf, agg in aggregates.items()},
        }
    finally:
        for path in tmp.values():
            path.unlink(missing_ok=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default=START.isoformat(), help="UTC start inclusive")
    parser.add_argument("--end", default=END.isoformat(), help="UTC end exclusive")
    parser.add_argument("--pairs", nargs="+", choices=INSTRUMENTS, default=list(INSTRUMENTS))
    parser.add_argument("--side", choices=("bid", "ask"), default="bid")
    parser.add_argument("--data-dir", type=Path, default=Path(__file__).resolve().parent / "data")
    args = parser.parse_args(argv)
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    if start >= end:
        parser.error("start must precede end")
    if end > datetime.now(timezone.utc).date():
        parser.error("end must not exceed today's UTC date; avoid incomplete candles")
    args.data_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = args.data_dir / f"manifest_{args.side}.json"
    prior = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    if prior and (prior.get("start") != args.start or prior.get("end") != args.end):
        print("Requested range differs from prior manifest; outputs will be overwritten after success", file=sys.stderr)
    manifest = {"schema": 1, "source": "Dukascopy via dukascopy-node", "tool_version": TOOL_VERSION,
                "start": args.start, "end": args.end, "end_exclusive": True, "timezone": "UTC",
                "side": args.side, "volume": "Dukascopy indicative quote volume (not centralized traded volume)",
                "missing_bars": "Not filled: forex weekends, holidays and missing source minutes stay absent",
                "symbols": prior.get("symbols", {}) if (prior.get("start") == args.start and prior.get("end") == args.end) else {}}
    try:
        for pair in args.pairs:
            files = []
            details = []
            for begin, bound in months(start, end):
                path, info = fetch_month(pair, args.side, begin, bound, args.data_dir)
                files.append((path, (begin, bound)))
                details.append(info)
            output = produce(pair, args.side, files, start, end, args.data_dir)
            manifest["symbols"][pair] = {"source_months": details, "outputs": output}
            print(f"READY {pair}: {output['1m']['rows']} 1m candles", flush=True)
            temp = manifest_path.with_suffix(".json.tmp")
            temp.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            temp.replace(manifest_path)
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1
    print(f"DONE: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
