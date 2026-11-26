import hashlib
import json
from pathlib import Path
import zipfile

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def load(symbol, cfg):
    directory = ROOT / cfg["manifest_directory"]
    records = json.loads((directory / "data_manifest.json").read_text())
    records += json.loads((directory / "repair_manifest.json").read_text())
    directory = ROOT / cfg["btc_cache" if symbol == "BTCUSDT" else "alt_cache"]
    start = pd.Timestamp(cfg["start"]).value // 10**6
    end = pd.Timestamp(cfg["end_exclusive"]).value // 10**6
    parts, rates = [], []
    for row in records:
        name = row["name"]
        if row["symbol"] != symbol or not ("-1m-" in name or "-fundingRate-" in name):
            continue
        path = directory / name
        if hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]:
            raise ValueError(f"Invalid checksum: {path}")
        with zipfile.ZipFile(path) as archive, archive.open(archive.namelist()[0]) as file:
            if "-1m-" in name:
                raw = pd.read_csv(file, header=None, usecols=range(6))
                raw[0] = pd.to_numeric(raw[0], errors="coerce")
                raw = raw.loc[raw[0].notna()].astype(float)
                raw[0] = np.where(raw[0] > 1e14, raw[0] // 1000, raw[0])
                parts.append(raw.loc[(raw[0] >= start) & (raw[0] < end)])
            else:
                rates.append(pd.read_csv(file, usecols=["calc_time", "last_funding_rate"]))
    market = pd.concat(parts, ignore_index=True).sort_values(0).to_numpy()
    if not np.array_equal(market[:, 0], np.arange(start, end, 60000)):
        raise ValueError(f"Minute coverage mismatch: {symbol}")
    prices = np.ascontiguousarray(market[:, 1:])
    assert np.isfinite(prices).all() and np.all(prices[:, :4] > 0)
    assert (prices[:, 1] >= np.maximum(prices[:, 0], prices[:, 3])).all()
    assert (prices[:, 2] <= np.minimum(prices[:, 0], prices[:, 3])).all()
    rates = pd.concat(rates)
    minutes = ((rates.calc_time.to_numpy(dtype=np.int64) - start) // 60000)
    valid = (minutes >= 0) & (minutes < len(prices))
    assert len(np.unique(minutes[valid])) == valid.sum()
    funding = np.zeros(len(prices))
    funding[minutes[valid]] = rates.last_funding_rate.to_numpy()[valid]
    return prices, np.r_[0., np.cumsum(funding)]


def aggregate(prices, minutes):
    blocks = prices[:len(prices) // minutes * minutes].reshape(-1, minutes, 5)
    return np.ascontiguousarray(np.column_stack((
        blocks[:, 0, 0], blocks[:, :, 1].max(axis=1), blocks[:, :, 2].min(axis=1),
        blocks[:, -1, 3], blocks[:, :, 4].sum(axis=1))))
