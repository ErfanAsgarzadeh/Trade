#!/usr/bin/env python3
"""Download five years of real 1-minute FX bid bars from HistData.com.

Fallback source for networks where the Dukascopy datafeed is unreachable.
HistData "ASCII M1" files are bid quotes stamped in EST *without* daylight
saving (fixed UTC-05:00); they are converted to UTC milliseconds here.

Outputs (forex/data/ohlcv/, not committed):
    EUR_USD_bid_1m.csv, GBP_USD_bid_1m.csv, USD_JPY_bid_1m.csv
    columns: timestamp,open,high,low,close,volume   (timestamp = UTC open, ms)
plus forex/data/manifest_histdata.json with SHA-256, row counts and gaps.

No candle is invented: weekends, holidays and missing minutes stay missing.
Python stdlib only.
"""
from __future__ import annotations

import argparse
import hashlib
import http.cookiejar
import io
import json
import re
import sys
import time
import urllib.parse
import urllib.request
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

PAIRS = ("EURUSD", "GBPUSD", "USDJPY")
EXTRA = ("XAUUSD", "XAGUSD", "SPXUSD", "NSXUSD", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD",
         "EURJPY", "GBPJPY", "EURGBP", "AUDJPY")
START = date(2021, 11, 12)
END = date(2026, 11, 12)  # exclusive
BASE = "https://www.histdata.com"
EST = timezone(timedelta(hours=-5))  # HistData: EST, no DST
MINUTE_MS = 60_000
HEADER = "timestamp,open,high,low,close,volume\n"
UA = "Mozilla/5.0 (research downloader)"


def file_name(pair: str) -> str:
    return f"{pair[:3]}_{pair[3:]}_bid_1m.csv"


def chunks(start: date, end: date, today: date):
    """Yearly archives for finished years, monthly ones for the current year."""
    for year in range(start.year, end.year + 1):
        if year < today.year:
            yield (year, None)
        else:
            for month in range(1, 13):
                if date(year, month, 1) >= end or date(year, month, 1) > today:
                    break
                yield (year, month)


class Client:
    def __init__(self):
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.opener.addheaders = [("User-Agent", UA)]

    def fetch(self, pair: str, year: int, month: int | None) -> bytes | None:
        path = f"/download-free-forex-historical-data/?/ascii/1-minute-bar-quotes/{pair.lower()}/{year}"
        if month:
            path += f"/{month}"
        page_url = BASE + path
        html = self.opener.open(page_url, timeout=60).read().decode("utf-8", "replace")
        fields = dict(re.findall(r'name="(tk|date|datemonth|platform|timeframe|fxpair)" id="[a-z]+" value="([^"]*)"', html))
        if "tk" not in fields:
            return None  # archive not published (yet)
        req = urllib.request.Request(BASE + "/get.php", data=urllib.parse.urlencode(fields).encode(),
                                     headers={"Referer": page_url, "User-Agent": UA})
        blob = self.opener.open(req, timeout=300).read()
        if not blob.startswith(b"PK"):
            return None
        return blob


def parse_zip(blob: bytes, lo_ms: int, hi_ms: int):
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        name = next(n for n in zf.namelist() if n.lower().endswith(".csv"))
        text = zf.read(name).decode("ascii")
    for line in text.splitlines():
        if not line.strip():
            continue
        stamp, o, h, l, c, v = line.split(";")
        dt = datetime.strptime(stamp, "%Y%m%d %H%M%S").replace(tzinfo=EST)
        ts = int(dt.timestamp() * 1000)
        if lo_ms <= ts < hi_ms:
            yield ts, o, h, l, c, v


def dedupe(rows: list[tuple]):
    """HistData repeats one hour around the autumn clock change; drop repeats."""
    out, same, diff = [], 0, 0
    for r in rows:
        if out and out[-1][0] == r[0]:
            if out[-1] == r:
                same += 1
            else:
                diff += 1
            continue
        out.append(r)
    return out, same, diff


def validate(rows: list[tuple]) -> None:
    prev = None
    for ts, o, h, l, c, _ in rows:
        fo, fh, fl, fc = map(float, (o, h, l, c))
        if ts % MINUTE_MS:
            raise ValueError(f"unaligned minute {ts}")
        if prev is not None and ts <= prev:
            raise ValueError(f"unsorted/duplicate minute {ts}")
        if min(fo, fh, fl, fc) <= 0 or fh < max(fo, fl, fc) or fl > min(fo, fh, fc):
            raise ValueError(f"invalid OHLC at {ts}")
        prev = ts


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=Path(__file__).resolve().parent / "data")
    ap.add_argument("--start", type=date.fromisoformat, default=START,
                    help="first day (warm-up history goes to a separate --out)")
    ap.add_argument("--end", type=date.fromisoformat, default=END)
    ap.add_argument("--pairs", nargs="+", default=list(PAIRS), choices=PAIRS + EXTRA)
    args = ap.parse_args()
    start, end = args.start, args.end
    lo = int(datetime(start.year, start.month, start.day, tzinfo=timezone.utc).timestamp() * 1000)
    hi = int(datetime(end.year, end.month, end.day, tzinfo=timezone.utc).timestamp() * 1000)
    today = datetime.now(timezone.utc).date()
    cache = args.out / "histdata_zip"
    cache.mkdir(parents=True, exist_ok=True)
    (args.out / "ohlcv").mkdir(parents=True, exist_ok=True)
    client = Client()
    mpath = args.out / "manifest_histdata.json"
    old = json.loads(mpath.read_text()) if mpath.is_file() else {}
    manifest = {"source": "HistData.com ASCII M1 (bid, EST fixed UTC-5 -> UTC)",
                "start": start.isoformat(), "end": end.isoformat(), "side": "bid", "symbols": old.get("symbols", {})}
    for pair in args.pairs:
        rows: list[tuple] = []
        archives = []
        for year, month in chunks(start, end, today):
            tag = f"{pair}_{year}" + (f"_{month:02d}" if month else "")
            zpath = cache / f"{tag}.zip"
            if not zpath.is_file():
                blob = None
                for attempt in range(5):
                    try:
                        blob = client.fetch(pair, year, month)
                        break
                    except Exception as exc:  # network hiccup -> back off
                        print(f"  {tag}: {exc}; retry {attempt + 1}", file=sys.stderr)
                        time.sleep(3 * (attempt + 1))
                if blob is None:
                    print(f"  {tag}: not available, skipped", file=sys.stderr)
                    continue
                zpath.write_bytes(blob)
            got = list(parse_zip(zpath.read_bytes(), lo, hi))
            archives.append({"archive": zpath.name, "rows_in_range": len(got), "sha256": sha256(zpath)})
            rows.extend(got)
            print(f"{tag}: {len(got)} rows", flush=True)
        rows.sort(key=lambda r: r[0])
        rows, dup_same, dup_diff = dedupe(rows)
        validate(rows)
        out = args.out / "ohlcv" / file_name(pair)
        tmp = out.with_suffix(".tmp")
        with tmp.open("w") as f:
            f.write(HEADER)
            for r in rows:
                f.write(",".join(map(str, r)) + "\n")
        tmp.replace(out)
        gaps = sum(1 for a, b in zip(rows, rows[1:]) if b[0] - a[0] > 3 * 86_400_000)
        manifest["symbols"][pair] = {
            "file": f"ohlcv/{out.name}", "rows": len(rows), "sha256": sha256(out),
            "first_ms": rows[0][0], "last_ms": rows[-1][0],
            "first_utc": datetime.fromtimestamp(rows[0][0] / 1000, timezone.utc).isoformat(),
            "last_utc": datetime.fromtimestamp(rows[-1][0] / 1000, timezone.utc).isoformat(),
            "gaps_over_3_days": gaps, "duplicate_minutes_identical": dup_same,
            "duplicate_minutes_conflicting_kept_first": dup_diff, "archives": archives}
        print(f"{pair}: {len(rows)} minutes -> {out}")
    (args.out / "manifest_histdata.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
