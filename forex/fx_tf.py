#!/usr/bin/env python3
"""Search across more timeframes and pick "good" strategies with pre-declared rules.

New timeframes: 15m, 30m, 2h, 8h, 12h, W1 (every family's 4h parameter grid re-used on each;
the London/Asia-range family is session-specific and stays on 1h).  Combined with the
1h/4h/D1 run of fx_best.py -> all nine timeframes.

Pre-declared "good strategy" rules (fixed before looking at results)
  selection uses 2021-11-12 .. 2024-12-31 ONLY:
    A  >= 60 trades over five years
    B  in-sample Sharpe >= 0.7
    C  at least 2 of the 3 years 2022, 2023, 2024 positive
    D  in-sample max drawdown <= 25 % at 1 % risk per trade
    E  neighbourhood: > 50 % of the same family/timeframe/symbol parameter sets profitable in-sample
  test: 2025-01-01 .. 2026-11-06, never used for selection
  luck check: the same rules on sign-flipped (edge-removed) streams -> how many pass by chance

Outputs: reports/fx_tf.json, reports/charts_tf/*.png, data/fx_tf_streams.npz
"""
from __future__ import annotations

import json
import os
import sys
import time
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fx_lab as fl  # noqa: E402
from fx_search_dd import SYMBOLS, maxdd  # noqa: E402

NEW_TF = ("15m", "30m", "2h", "8h", "12h", "W1")
RISK = 0.01
LAB = None


def tf_items():
    base = [x for x in fl.families() if x[1] == "4h"]
    out = []
    for tf in NEW_TF:
        for fam, _, sp, ex in base:
            sp2 = dict(sp)
            if "tf" in sp2:
                sp2["tf"] = tf
            out.append((fam, tf, sp2, ex))
    return out


def init():
    global LAB
    LAB = fl.Lab(HERE / "data", SYMBOLS)


def work(item):
    idx, fam, tf, sp, ex = item
    out = []
    for s in SYMBOLS:
        b = LAB.get_bars(s, tf)
        daily, levd, tr = LAB.run(s, tf, fl.FAM[fam](b, sp), ex)
        out.append((idx, s, daily.astype(np.float32), len(tr)))
    return out


def eq_of(x):
    return np.cumprod(np.clip(1 + RISK * x, 1e-9, None))


def cagr_of(x):
    return float(eq_of(x)[-1] ** (365.25 / len(x)) - 1)


def sharpe_rows(X):
    return X.mean(1) / (X.std(1) + 1e-12) * np.sqrt(365.25)


def select(S, meta, yr, label):
    IS = yr < 2025
    X = S[:, IS]
    trades = np.array([m["trades"] for m in meta])
    sh = sharpe_rows(X)
    pos_years = sum((S[:, yr == y].sum(1) > 0).astype(int) for y in (2022, 2023, 2024))
    eqs = np.cumprod(np.clip(1 + RISK * X, 1e-9, None), axis=1)
    dd = np.max(1 - eqs / np.maximum.accumulate(eqs, axis=1), axis=1)
    prof = X.sum(1) > 0
    key = np.array([f"{m['family']}|{m['tf']}|{m['symbol']}" for m in meta])
    nb = pd.Series(prof).groupby(key).transform("mean").to_numpy()
    ok = (trades >= 60) & (sh >= 0.7) & (pos_years >= 2) & (dd <= 0.25) & (nb > 0.5)
    return np.where(ok)[0], sh, dd, nb


def main():
    t0 = time.time()
    items = [(i, *x) for i, x in enumerate(tf_items())]
    print(f"{len(items)} configs x {len(SYMBOLS)} symbols = {len(items) * len(SYMBOLS)} new strategies", flush=True)
    npz = HERE / "data" / "fx_tf_streams.npz"
    if not (npz.is_file() and (HERE / "data" / "fx_tf_meta.json").is_file()):
        part_dir = HERE / "data" / "fx_tf_parts"
        part_dir.mkdir(exist_ok=True)
        for tf in NEW_TF:  # one timeframe at a time, saved to disk -> resumable
            part = part_dir / f"{tf}.npz"
            if part.is_file():
                continue
            sub = [it for it in items if it[2] == tf]
            t1 = time.time()
            with Pool(os.cpu_count(), initializer=init, maxtasksperchild=200) as pool:
                res = [r for chunk in pool.imap(work, sub, chunksize=1) for r in chunk]
            np.savez_compressed(part, S=np.stack([r[2] for r in res]),
                                idx=np.array([r[0] for r in res]), trades=np.array([r[3] for r in res]),
                                sym=np.array([r[1] for r in res]))
            print(f"  {tf}: {len(res)} strategies in {time.time() - t1:.0f}s", flush=True)
            del res
        S_parts, meta_new = [], []
        for tf in NEW_TF:
            z = np.load(part_dir / f"{tf}.npz")
            S_parts.append(z["S"])
            for i, s, n in zip(z["idx"], z["sym"], z["trades"]):
                fam, tf_, sp, ex = items[int(i)][1:]
                meta_new.append(dict(idx=int(i), symbol=str(s), family=fam, tf=tf_, trades=int(n),
                                     params={k: (list(v) if isinstance(v, tuple) else v) for k, v in sp.items()},
                                     exits=ex))
        np.savez_compressed(npz, S=np.concatenate(S_parts))
        (HERE / "data" / "fx_tf_meta.json").write_text(json.dumps(meta_new))
        del S_parts
    S_new = np.load(npz)["S"]
    meta_new = json.loads((HERE / "data" / "fx_tf_meta.json").read_text())
    S_old = np.load(HERE / "data" / "fx_best_streams.npz")["S"]
    meta_old = json.loads((HERE / "data" / "fx_best_meta.json").read_text())
    S = np.concatenate([S_old, S_new]).astype(np.float32)
    meta = [dict(m, src="fx_best") for m in meta_old] + [dict(m, src="fx_tf") for m in meta_new]
    del S_old, S_new
    day0 = fl.sfx.ms(fl.Lab.START) // fl.DAY_MS
    days = pd.to_datetime((np.arange(S.shape[1]) + day0) * fl.DAY_MS, unit="ms")
    yr = days.year.values
    IS, OOS = yr < 2025, yr >= 2025

    # ---------- overview by timeframe
    tfs = ("15m", "30m", "1h", "2h", "4h", "8h", "12h", "D1", "W1")
    tf_arr = np.array([m["tf"] for m in meta])
    trades = np.array([m["trades"] for m in meta])
    full_c = np.expm1(np.log(np.clip(1 + RISK * S, 1e-9, None)).sum(1) / (S.shape[1] / 365.25))
    is_c = np.expm1(np.log(np.clip(1 + RISK * S[:, IS], 1e-9, None)).sum(1) / (IS.sum() / 365.25))
    oos_c = np.expm1(np.log(np.clip(1 + RISK * S[:, OOS], 1e-9, None)).sum(1) / (OOS.sum() / 365.25))
    by_tf = {}
    for tf in tfs:
        js = np.where((tf_arr == tf) & (trades >= 30))[0]
        if len(js):
            by_tf[tf] = dict(strategies=int(len(js)), share_profitable_5y=round(float((full_c[js] > 0).mean()), 3),
                             share_profitable_is=round(float((is_c[js] > 0).mean()), 3),
                             share_profitable_oos=round(float((oos_c[js] > 0).mean()), 3),
                             median_cagr=round(float(np.median(full_c[js])), 4),
                             best_cagr=round(float(full_c[js].max()), 4))
    print(json.dumps(by_tf, indent=0), flush=True)

    # ---------- selection on in-sample only, then the untouched test
    sel, sh, dd, nb = select(S, meta, yr, "real")
    # luck check: sign flip in 21-day blocks (edge removed, volatility kept)
    rng = np.random.default_rng(0)
    blk = np.arange(S.shape[1]) // 21
    n_null = []
    for k in range(3):
        sg = rng.choice([-1.0, 1.0], size=(S.shape[0], blk.max() + 1)).astype(np.float32)[:, blk]
        selN, *_ = select(S * sg, meta, yr, "null")
        n_null.append(int(len(selN)))
        del sg
    print("selected (real):", len(sel), "by chance (null):", n_null, flush=True)

    cands = []
    for j in sel:
        m = meta[j]
        cands.append(dict(j=int(j), symbol=m["symbol"], family=m["family"], tf=m["tf"], params=m["params"],
                          exits=m["exits"], trades=m["trades"], is_sharpe=round(float(sh[j]), 2),
                          is_cagr=round(float(is_c[j]), 4), is_maxdd=round(float(dd[j]), 4),
                          neighbourhood_profitable=round(float(nb[j]), 2),
                          oos_cagr=round(float(oos_c[j]), 4), full_cagr=round(float(full_c[j]), 4),
                          oos_sharpe=round(float(sharpe_rows(S[j:j + 1, OOS])[0]), 2),
                          oos_maxdd=round(maxdd(eq_of(S[j, OOS])), 4),
                          full_maxdd=round(maxdd(eq_of(S[j])), 4),
                          yearly={int(y): round(float(eq_of(S[j, yr == y])[-1] - 1), 4) for y in range(2022, 2027)}))
    cands.sort(key=lambda c: -c["is_sharpe"])
    passed = [c for c in cands if c["oos_cagr"] > 0]
    # keep one per family/timeframe/symbol (the best in-sample) so the list is not 20 copies of one idea
    seen, final = set(), []
    for c in passed:
        k = (c["family"], c["tf"], c["symbol"])
        if k not in seen:
            seen.add(k)
            final.append(c)
    # equal-risk book of the distinct finalists (each 1 % per trade)
    book = None
    if final:
        J = [c["j"] for c in final]
        R = S[J].sum(0)
        e = eq_of(R)
        ser = pd.Series(e, index=days)
        ye = ser.groupby(ser.index.year).last()
        book = dict(members=len(J), cagr=round(cagr_of(R), 4), max_dd=round(maxdd(e), 4),
                    oos_cagr=round(cagr_of(R[OOS]), 4), oos_maxdd=round(maxdd(eq_of(R[OOS])), 4),
                    yearly={int(k): round(float(v), 4) for k, v in (ye / ye.shift(1).fillna(1.0) - 1).items()},
                    note="members were chosen with 2025-26 already known to be positive (survivor list)")
        np.save(HERE / "data" / "fx_tf_book.npy", R.astype(np.float32))
    report = dict(rules=__doc__, strategies_total=int(S.shape[0]), timeframes=tfs, by_timeframe=by_tf,
                  selected_in_sample=int(len(sel)), selected_by_chance_null=n_null,
                  selected_positive_oos=len(passed),
                  share_selected_positive_oos=round(len(passed) / max(1, len(sel)), 3),
                  share_all_positive_oos=round(float((oos_c[trades >= 30] > 0).mean()), 3),
                  candidates_in_sample_ranked=cands[:200], finalists_distinct=final, finalists_book=book,
                  runtime_s=round(time.time() - t0, 1))
    (HERE / "reports" / "fx_tf.json").write_text(json.dumps(report, indent=1, default=float) + "\n")
    np.save(HERE / "data" / "fx_tf_final_idx.npy", np.array([c["j"] for c in final], dtype=np.int64))
    print("selected:", len(sel), "positive OOS:", len(passed), "distinct finalists:", len(final))
    for c in final[:20]:
        print(c["symbol"], c["tf"], c["family"], c["params"], c["exits"], "IS", c["is_cagr"], c["is_sharpe"],
              "| OOS", c["oos_cagr"], c["oos_sharpe"], "| 5y", c["full_cagr"], "DD", c["full_maxdd"])
    print(f"total {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
