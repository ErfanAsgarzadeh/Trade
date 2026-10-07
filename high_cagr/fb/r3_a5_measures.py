"""Causal statistical regime measures on 4h closes (row i uses closes <= i)."""
import numpy as np, pandas as pd

def roll_r2(lp, n):
    x = np.arange(n) - (n - 1) / 2; sxx = (x**2).sum()
    out = np.full(len(lp), np.nan)
    s = pd.Series(lp)
    my = s.rolling(n).mean().to_numpy()
    sxy = np.full(len(lp), np.nan); syy = (s**2).rolling(n).sum().to_numpy() - n * my**2
    # sum x*y via convolution
    conv = np.convolve(lp, x[::-1], mode='full')[:len(lp)]
    sxy = conv; sxy[:n-1] = np.nan
    with np.errstate(all='ignore'):
        out = sxy**2 / (sxx * syy)
    return out

def roll_vr(r, n, q):
    """Lo-MacKinlay VR(q) over last n returns (overlapping q-sums vs q*var1)."""
    s = pd.Series(r)
    v1 = s.rolling(n).var().to_numpy()
    rq = s.rolling(q).sum()
    vq = rq.rolling(n - q + 1).var().to_numpy()
    with np.errstate(all='ignore'):
        return vq / (q * v1)

def roll_ac(r, n, k):
    s = pd.Series(r)
    return s.rolling(n).corr(s.shift(k)).to_numpy()

def roll_hurst(r, n):
    """R/S Hurst estimate: average over sub-block sizes of log(R/S)/log(size) pooled by regression, n bars."""
    out = np.full(len(r), np.nan)
    sizes = [8, 16, 32, n]
    for i in range(n - 1, len(r)):
        w = r[i - n + 1:i + 1]
        if np.isnan(w).any(): continue
        ls, lr = [], []
        for m in sizes:
            k = n // m; rs = []
            for j in range(k):
                b = w[j*m:(j+1)*m]; d = np.cumsum(b - b.mean()); sd = b.std()
                if sd > 0: rs.append((d.max() - d.min()) / sd)
            if rs: ls.append(np.log(m)); lr.append(np.log(np.mean(rs)))
        if len(ls) >= 3: out[i] = np.polyfit(ls, lr, 1)[0]
    return out

def rv_pct(r, n, lookback):
    rv = pd.Series(r).rolling(n).std()
    return rv.rolling(lookback).rank(pct=True).to_numpy()

def measures(close):
    c = np.asarray(close, float); lp = np.log(c)
    r = np.diff(lp, prepend=np.nan)
    return dict(r2_30=roll_r2(lp, 30), r2_60=roll_r2(lp, 60),
                vr6=roll_vr(r, 120, 6), vr3=roll_vr(r, 60, 3),
                ac1=roll_ac(r, 60, 1), ac6=roll_ac(r, 120, 6),
                hurst=roll_hurst(r, 128), rvp=rv_pct(r, 20, 540))
