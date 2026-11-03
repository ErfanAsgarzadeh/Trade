"""OFFLINE ONLY: walk-forward XGBoost versus 1D-CNN gate for Shahin's frozen 4h strategy.

The two models use only previously CLOSED four-hour bars. Validation thresholds
are replayed by the original minute engine. Never imported by the live/paper bot.
"""
from __future__ import annotations
import argparse
import json
import random
from pathlib import Path
import numpy as np
import pandas as pd
from high_cagr import run_suite as rs
from high_cagr.kernel import simulate

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "high_cagr" / "output"
BASE_ID = "HC__FIVE__standard__4h__N10__DONCHIAN10__PY1__R0.0075__P4"
STEP_MS = 4 * 60 * 60 * 1000
LOOKBACK = 48
EMBARGO_DAYS = 14
THRESHOLDS = (.30, .35, .40, .45, .50, .55, .60)
YEARS = (2024, 2025, 2026)


def utc_ms(value: str) -> int:
    return int(pd.Timestamp(value, tz="UTC").timestamp() * 1000)


def ensure_inputs() -> None:
    missing = []
    for symbol in rs.SYMBOLS:
        for name in ("prices.npy", "funding.npy", "4h_standard.npz"):
            p = ROOT / "high_cagr" / "prepared" / symbol / name
            if not p.is_file():
                missing.append(str(p))
    if not (OUT / "failure_positions_full.csv").is_file():
        missing.append(str(OUT / "failure_positions_full.csv"))
    if missing:
        raise FileNotFoundError(
            "Restore data using high_cagr/restore_inputs.py and high_cagr/prepare.py. Missing:\n"
            + "\n".join(missing[:12])
        )


def sequence(frame: pd.DataFrame, ix: int, side: int, symbol_index: int,
             lookback: int = LOOKBACK) -> np.ndarray | None:
    """Causal feature tensor using at most row ix, normalized within its own window."""
    if ix < lookback or side not in (-1, 1):
        return None
    vals = frame.iloc[ix - lookback:ix + 1][
        ["open", "high", "low", "close", "volume", "atr", "kijun"]
    ].to_numpy(dtype=np.float64)
    if not np.isfinite(vals).all() or (vals[:, :4] <= 0).any():
        return None
    op, high, low, close, vol, atr, kijun = vals[1:].T
    prev = vals[:-1, 3]
    if (prev <= 0).any():
        return None
    lv = np.log1p(np.maximum(0, vol))
    lv = (lv - lv.mean()) / max(lv.std(), .1)
    base = np.column_stack((
        side * np.log(close / prev),
        side * (close - op) / prev,
        (high - low) / prev,
        (high - np.maximum(op, close)) / prev,
        (np.minimum(op, close) - low) / prev,
        lv,
        atr / close,
        side * (close - kijun) / close,
    ))
    static = np.zeros((lookback, len(rs.SYMBOLS) + 1), dtype=np.float64)
    static[:, 0] = side
    static[:, symbol_index + 1] = 1.
    x = np.concatenate((base, static), axis=1)
    return np.clip(x, -10, 10).astype(np.float32) if np.isfinite(x).all() else None


def bar_index(frame: pd.DataFrame, decision_ms: int) -> int:
    """Last fully closed four-hour bar; excludes the bar running at decision time."""
    return int(np.searchsorted(
        frame["timestamp"].to_numpy(dtype=np.int64) + STEP_MS,
        decision_ms, side="right"
    ) - 1)


def summarize_sequence(x: np.ndarray) -> np.ndarray:
    """Tabular summary of the SAME causal window given to CNN."""
    d = x[:, :8]
    return np.concatenate((
        d.mean(axis=0), d.std(axis=0), d.min(axis=0), d.max(axis=0),
        d[-1], d[-6:].mean(axis=0), x[-1, 8:]
    )).astype(np.float32)


def build_training(positions: pd.DataFrame, frames: dict):
    tensors, targets, retained = [], [], []
    symbols = {s: i for i, s in enumerate(rs.SYMBOLS)}
    for idx, p in positions.iterrows():
        sym = str(p["symbol"])
        if sym not in symbols:
            continue
        side = 1 if p["side"] == "LONG" else -1
        frame = frames[sym, "4h", "standard"]
        x = sequence(frame, bar_index(frame, int(p["entry_ts"])), side, symbols[sym])
        if x is not None:
            tensors.append(x)
            targets.append(int(float(p["net_r"]) > 0))
            retained.append(idx)
    if not tensors:
        raise ValueError("No causal training sequences")
    return np.stack(tensors), np.asarray(targets, dtype=np.int64), np.asarray(retained)


def predict_xgb(train_x, train_y, apply_x):
    from xgboost import XGBClassifier
    if len(np.unique(train_y)) != 2:
        raise ValueError("Each training fold must have both classes")
    model = XGBClassifier(
        n_estimators=130, max_depth=3, learning_rate=.04, subsample=.85,
        colsample_bytree=.85, min_child_weight=8, reg_lambda=5.,
        tree_method="hist", n_jobs=2, random_state=71, eval_metric="logloss"
    )
    model.fit(np.stack([summarize_sequence(x) for x in train_x]), train_y)
    return model.predict_proba(np.stack([summarize_sequence(x) for x in apply_x]))[:, 1]


def predict_cnn(train_x, train_y, apply_x):
    import torch
    from torch import nn
    torch.manual_seed(71)
    torch.set_num_threads(2)
    random.seed(71)
    np.random.seed(71)
    model = nn.Sequential(
        nn.Conv1d(train_x.shape[2], 24, kernel_size=5, padding=2),
        nn.ReLU(), nn.Conv1d(24, 24, kernel_size=3, padding=1),
        nn.ReLU(), nn.AdaptiveAvgPool1d(1), nn.Flatten(), nn.Linear(24, 1)
    )
    optimizer = torch.optim.AdamW(model.parameters(), lr=.001, weight_decay=.01)
    pos_weight = min(3., max(.4, (len(train_y) - train_y.sum()) / max(1, train_y.sum())))
    loss_fn = nn.BCEWithLogitsLoss(pos_weight=torch.tensor([pos_weight], dtype=torch.float32))
    X = torch.tensor(train_x.transpose(0, 2, 1).copy(), dtype=torch.float32)
    Y = torch.tensor(train_y[:, None], dtype=torch.float32)
    for _ in range(22):
        model.train()
        for ids in torch.randperm(len(Y)).split(128):
            optimizer.zero_grad()
            loss = loss_fn(model(X[ids]), Y[ids])
            loss.backward()
            optimizer.step()
    model.eval()
    output = []
    with torch.no_grad():
        chunks = np.array_split(apply_x, max(1, (len(apply_x) + 1023) // 1024))
        for chunk in chunks:
            if len(chunk):
                t = torch.tensor(chunk.transpose(0, 2, 1).copy(), dtype=torch.float32)
                output.append(torch.sigmoid(model(t))[:, 0].numpy())
    return np.concatenate(output)


def indices_for_year(year: int):
    a = max(rs.START, utc_ms(f"{year}-01-01"))
    b = min(rs.END, utc_ms(f"{year + 1}-01-01"))
    return (a - rs.START) // 60000, (b - rs.START) // 60000


def apply_gate(original: np.ndarray, prob: np.ndarray,
               locations: np.ndarray, threshold: float) -> np.ndarray:
    if threshold <= 0:
        return original
    result = original.copy()
    selected = prob < threshold
    if selected.any():
        result[locations[selected, 0], locations[selected, 1], 0] = 0.
    return np.ascontiguousarray(result)


def score_signals(signals: np.ndarray, frames: dict, start_ms: int, end_ms: int):
    sym_rows, times = np.nonzero(signals[:, :, 0])
    ms = rs.START + times * STEP_MS
    keep = (ms >= start_ms) & (ms < end_ms)
    xs, locations = [], []
    for s, t in zip(sym_rows[keep], times[keep]):
        frame = frames[rs.SYMBOLS[int(s)], "4h", "standard"]
        x = sequence(frame, bar_index(frame, int(rs.START + t * STEP_MS)),
                     int(signals[s, t, 0]), int(s))
        if x is not None:
            xs.append(x)
            locations.append((int(s), int(t)))
        # Unscorable signals are left untouched, not silently rejected.
    if not xs:
        raise ValueError("No causal features available for candidate signals")
    return np.stack(xs), np.asarray(locations, dtype=np.int64)


def replay(sig, prices, funding, bars, begin, end):
    a, trades, curve = simulate(prices, funding, sig, bars, rs.START, begin, end,
                                .0075, 4, 240, True)
    return rs.summarize(a, trades, curve, begin, end, rs.SYMBOLS)


def select_threshold(sig, locations, prob, prices, funding, bars, begin, end):
    baseline = replay(sig, prices, funding, bars, begin, end)
    selected, best, selected_row = 0., baseline["net_profit"], baseline
    for threshold in THRESHOLDS:
        gated = apply_gate(sig, prob, locations, threshold)
        row = replay(gated, prices, funding, bars, begin, end)
        if (row["root_entries"] >= max(30, int(.60 * baseline["root_entries"]))
            and row["max_dd_pct"] <= min(35., baseline["max_dd_pct"])
            and row["net_profit"] > best):
            selected, best, selected_row = threshold, row["net_profit"], row
    return selected, selected_row


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUT / "ml_trade_filter_results.json")
    args = parser.parse_args()
    ensure_inputs()
    positions = pd.read_csv(OUT / "failure_positions_full.csv").sort_values(
        "entry_ts"
    ).reset_index(drop=True)
    case = next(c for c in rs.grid() if c["id"] == BASE_ID)
    frames = rs.load_frames()
    signals, bars, step = rs.inputs(case, frames)
    assert step == 240
    prices = np.stack([
        np.load(ROOT / "high_cagr" / "prepared" / s / "prices.npy", mmap_mode="r")
        for s in rs.SYMBOLS
    ])
    funding = np.stack([
        np.load(ROOT / "high_cagr" / "prepared" / s / "funding.npy", mmap_mode="r")
        for s in rs.SYMBOLS
    ])
    train_x, labels, retained = build_training(positions, frames)
    aligned = positions.iloc[retained].reset_index(drop=True)
    embargo_ms = EMBARGO_DAYS * 86400000
    results = {}
    for year in YEARS:
        val_start = utc_ms(f"{year - 1}-01-01")
        test_start = utc_ms(f"{year}-01-01")
        test_end = min(rs.END, utc_ms(f"{year + 1}-01-01"))
        train_indices = np.where(
            aligned["exit_ts"].to_numpy() < val_start - embargo_ms
        )[0]
        if len(train_indices) < 100 or len(np.unique(labels[train_indices])) < 2:
            raise ValueError(f"Insufficient historical training trades for {year}: {len(train_indices)}")
        val_x, val_locs = score_signals(signals, frames, val_start, test_start)
        test_x, test_locs = score_signals(signals, frames, test_start, test_end)
        vb, ve = indices_for_year(year - 1)
        tb, te = indices_for_year(year)
        baseline = replay(signals, prices, funding, bars, tb, te)
        results[str(year)] = dict(baseline=baseline, training_trades=int(len(train_indices)),
                                  validation_year=year - 1,
                                  validation_candidates=len(val_x), test_candidates=len(test_x))
        for name, model in (("xgboost", predict_xgb), ("cnn_1d", predict_cnn)):
            p = model(train_x[train_indices], labels[train_indices],
                      np.concatenate((val_x, test_x)))
            threshold, validation = select_threshold(
                signals, val_locs, p[:len(val_x)], prices, funding, bars, vb, ve
            )
            gated = apply_gate(signals, p[len(val_x):], test_locs, threshold)
            test = replay(gated, prices, funding, bars, tb, te)
            results[str(year)][name] = dict(
                threshold=threshold, validation_net_usd=validation["net_profit"],
                test=test,
                rejected_candidates=int((p[len(val_x):] < threshold).sum()) if threshold else 0
            )
            print(year, name, "threshold", threshold, "test_net", test["net_profit"],
                  "baseline_net", baseline["net_profit"], flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(
        status="historical_research_only", historical_end_exclusive="2026-10-05",
        baseline_id=BASE_ID, frozen_baseline_rules=True,
        source="failure_positions_full.csv + restored 4h features + 1m replay",
        limitations=[
            "Original winning portfolio and symbols were previously selected using these years",
            "Only historically accepted baseline trades have outcome labels (selection bias)",
            "Scores are NOT calibrated probabilities; thresholds tuned only on earlier validation",
            "Each test year is replayed with fresh $10k equity, not a continuous compounded portfolio",
            "Binance historical candles/funding are not an LBank-execution validation"
        ], folds=results
    )
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False))
    print("WROTE", args.output)


if __name__ == "__main__":
    main()
