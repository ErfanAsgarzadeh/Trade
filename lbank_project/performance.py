"""Read-only performance summary of the three bots for the dashboard (closed trades + equity snapshots)."""
from __future__ import annotations
import json, math, time
from pathlib import Path
import pandas as pd

NAMES = {"main": "Shahin", "c3": "Mojsavar", "pa": "Ghoghnous"}


def stats(pnls: list[float]) -> dict:
    n = len(pnls);w = [p for p in pnls if p > 0];l = [p for p in pnls if p <= 0]
    gl = -sum(l)
    return dict(trades=n, wins=len(w), win_rate=(len(w) / n * 100) if n else None, total=sum(pnls),
                profit_factor=(sum(w) / gl) if gl > 0 else None, avg_win=(sum(w) / len(w)) if w else None,
                avg_loss=(sum(l) / len(l)) if l else None, best=max(pnls) if pnls else None, worst=min(pnls) if pnls else None)


def read_snapshots(path: Path, limit: int = 2500) -> list[dict]:
    if not path.is_file():return []
    rows = []
    for line in path.read_text().splitlines():
        try:rows.append(json.loads(line))
        except Exception:pass
    step = max(1, len(rows) // limit)
    return rows[::step] + ([rows[-1]] if rows and (len(rows) - 1) % step else [])


def drawdown(values: list[float]) -> tuple[float, float]:
    peak, worst = -math.inf, 0.
    for v in values:
        peak = max(peak, v);worst = min(worst, v / peak - 1 if peak > 0 else 0.)
    cur = values[-1] / max(values) - 1 if values else 0.
    return cur * 100, worst * 100


def summarize(trades: list[dict], seed: float, snapshots: list[dict], now: float | None = None) -> dict:
    """trades: dicts with bot, symbol, side, pnl, closed (unix s), optional entry/exit/reason."""
    now = now or time.time();out = {"seed": seed}
    out["bots"] = {b: dict(name=NAMES[b], **stats([t["pnl"] for t in trades if t["bot"] == b]),
                           pnl_7d=sum(t["pnl"] for t in trades if t["bot"] == b and t["closed"] >= now - 7 * 86400),
                           pnl_30d=sum(t["pnl"] for t in trades if t["bot"] == b and t["closed"] >= now - 30 * 86400)) for b in NAMES}
    out["all"] = dict(**stats([t["pnl"] for t in trades]), pnl_7d=sum(t["pnl"] for t in trades if t["closed"] >= now - 7 * 86400),
                      pnl_30d=sum(t["pnl"] for t in trades if t["closed"] >= now - 30 * 86400))
    cum, curve = seed, [dict(t=trades[0]["closed"] - 1, equity=seed)] if trades else []
    for t in trades:
        cum += t["pnl"];curve.append(dict(t=t["closed"], equity=cum))
    out["realized_curve"] = curve[-2000:]
    months, start = {}, seed
    if trades:
        df = pd.DataFrame(trades);df["m"] = pd.to_datetime(df.closed, unit="s").dt.strftime("%Y-%m")
        for m, g in df.groupby("m"):
            row = {b: float(g[g.bot == b].pnl.sum()) for b in NAMES};row["total"] = float(g.pnl.sum());row["pct"] = row["total"] / start * 100 if start > 0 else None
            row["trades"] = int(len(g));row["win_rate"] = float((g.pnl > 0).mean() * 100);months[m] = row;start += row["total"]
    out["monthly"] = months
    days = {}
    for t in trades:
        if t["closed"] >= now - 60 * 86400:
            d = time.strftime("%Y-%m-%d", time.gmtime(t["closed"]));r = days.setdefault(d, {b: 0. for b in NAMES});r[t["bot"]] += t["pnl"]
    out["daily"] = days
    out["snapshots"] = snapshots
    vals = [s["equity"] for s in snapshots] or [c["equity"] for c in curve]
    out["drawdown_now"], out["drawdown_max"] = drawdown(vals) if vals else (0., 0.)
    out["recent"] = [dict(t, name=NAMES[t["bot"]]) for t in trades[-150:][::-1]]
    out["first_trade"] = trades[0]["closed"] if trades else None
    return out
